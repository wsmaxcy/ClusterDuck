"""
MySQL InnoDB Cluster Management GUI
===================================
Re-implementation of the original PowerShell/WinForms tool using **Python 3.11**
and **customtkinter** for a modern dark-mode interface with animated LED status
icons.

Requirements
------------
* Python ≥ 3.9 on Windows
* `pip install customtkinter pillow psutil`
* MySQL Shell (`mysqlsh`) available in %PATH%
* LED images in an `img/` folder (LED.png, greenLED.png, yellowLED.png, redLED.png, blueLED.png)

Run with:
    python mysql_cluster_gui.py
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
from tkinter import messagebox  # add this at the top
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List

import customtkinter as ctk
from PIL import Image

###############################################################################
# -- utility helpers --
###############################################################################

HERE = Path(__file__).resolve().parent
IMG  = HERE / "img"

def get_led_color(status: str, role: str = "") -> str:
    status = status.upper()
    if status == "ONLINE":
        return "green"
    elif status in {"RECOVERING", "RECOVERY", "JOINING"}:
        return "yellow"
    else:
        return "red"

def resource_path(relative_path: str) -> Path:
    """Get the absolute path to a resource, compatible with PyInstaller."""
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).resolve().parent / relative_path

def center_window(win, width: int | None = None, height: int | None = None):
    """
    Re-position *win* so that it appears centred on the primary display.

    If *width* / *height* are not provided, the function asks Tk for the
    window’s current size (after an `update_idletasks()`).
    """
    win.update_idletasks()                           # be sure geometry is known

    if width  is None: width  = win.winfo_width()
    if height is None: height = win.winfo_height()

    screen_w  = win.winfo_screenwidth()
    screen_h  = win.winfo_screenheight()
    x = (screen_w  // 2) - (width  // 2)
    y = (screen_h // 2) - (height // 2)

    win.geometry(f"{width}x{height}+{x}+{y}")


IMG = resource_path("img")

class LEDManager:
    """Caches PIL images and handles blink animation via `after`."""

    def __init__(self, root: ctk.CTk):
        self.root         = root
        self._cache: Dict[str, ctk.CTkImage] = {}
        self._blink_jobs: Dict[str, str]     = {}   # widget->after-id
        self._blink_state: Dict[str, bool]   = {}


    def _load(self, filename: str) -> ctk.CTkImage:
        if filename not in self._cache:
            self._cache[filename] = ctk.CTkImage(Image.open(IMG / filename))
        return self._cache[filename]

    def set(self, widget: ctk.CTkLabel, filename: str, blink: bool = False):
        """Apply image; if *blink* toggle between image and blank LED.png."""
        self.stop(widget)

        if blink:
            on = self._load(filename)
            off = self._load("LED.png")
            self._blink_state[widget] = False

            def _step():
                if not widget.winfo_exists():
                    return  # Widget destroyed, stop blinking

                self._blink_state[widget] = not self._blink_state[widget]
                img = on if self._blink_state[widget] else off
                try:
                    widget.configure(image=img)
                    widget.image = img
                except Exception as e:
                    print(f"[LEDManager] Error updating LED: {e}")
                    return

                job_id = self.root.after(500, _step)
                self._blink_jobs[widget] = job_id

            _step()  # Start blinking
        else:
            # Just set the image statically
            try:
                img = self._load(filename)
                widget.configure(image=img)
                widget.image = img
            except Exception as e:
                print(f"[LEDManager] Error setting static LED: {e}")

        # ------------------------------------------------------------------
    def blink_between(self, widget: ctk.CTkLabel,
                      file_a: str, file_b: str,
                      interval: int = 500):
        """
        Blink by toggling between *file_a* and *file_b* instead of
        the old “on / blank” style.
        """
        self.stop(widget)                       # cancel any prior blink

        img_a = self._load(file_a)
        img_b = self._load(file_b)
        self._blink_state[widget] = False

        def _step():
            if not widget.winfo_exists():       # widget was destroyed
                return
            self._blink_state[widget] = not self._blink_state[widget]
            img = img_a if self._blink_state[widget] else img_b
            widget.configure(image=img)
            widget.image = img                  # keep reference
            job_id = self.root.after(interval, _step)
            self._blink_jobs[widget] = job_id

        _step()



    def stop(self, widget: ctk.CTkLabel):
        job_id = self._blink_jobs.pop(widget, None)
        if job_id:
            self.root.after_cancel(job_id)
        self._blink_state.pop(widget, None)


###############################################################################
# -- MySQL Shell interaction helpers --
###############################################################################

def run_mysqlsh(uri: str, js: str) -> str:
    """
    Run mysqlsh in --batch mode.  If the shell exits with non-zero status,
    raise RuntimeError so callers can handle it cleanly.
    """
    env = os.environ.copy()
    env["MYSQLSH_WARN_PASSWORD"] = "0"           # hide CLI-password warning

    result = subprocess.run(
        ["mysqlsh", "--uri", uri, "--js", "-e", js],
        capture_output=True,
        text=True,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW
    )

    # Drop only the "Using a password ..." warning
    stderr_lines = [
        ln for ln in result.stderr.strip().splitlines()
        if "can be insecure" not in ln
    ]
    stderr_clean = "\n".join(stderr_lines).strip()

    if result.returncode != 0:
        # Any mysqlsh failure bubbles up as an exception
        raise RuntimeError(stderr_clean or "mysqlsh exited with code "
                         f"{result.returncode}")

    return result.stdout.strip()



def get_cluster_status(uri: str) -> str:
    """Return raw JSON string from dba.getCluster().status()."""
    raw = run_mysqlsh(uri, "print(JSON.stringify(dba.getCluster().status()))")
    return raw


def format_cluster_status(raw: str) -> str:
    """Try to pretty-print the cluster JSON. Fall back to raw if needed."""
    try:
        json_start = raw.find('{')
        json_end = raw.rfind('}') + 1
        cleaned_json = raw[json_start:json_end]
        obj = json.loads(cleaned_json)
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"[Raw Cluster Output]\n{raw.strip()}"


###############################################################################
# -- Login dialog --
###############################################################################

class LoginDialog(ctk.CTkToplevel):
    def __init__(self, master: ctk.CTk):
        super().__init__(master)
        self.title("Login")
        self.geometry("200x270")
        self.grab_set()
        self.resizable(False, False)
        center_window(self, 200, 270)

         # 🌟 Add this block to set the icon
        icon_path = IMG / "icon.ico"
        if icon_path.exists():
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        self.user_var = ctk.StringVar()
        self.pass_var = ctk.StringVar()
        self.host_var = ctk.StringVar(value="localhost")

        ctk.CTkLabel(self, text="User:").pack(pady=(10, 0))
        ctk.CTkEntry(self, textvariable=self.user_var).pack()

        ctk.CTkLabel(self, text="Password:").pack(pady=(10, 0))
        ctk.CTkEntry(self, textvariable=self.pass_var, show="*").pack()

        ctk.CTkLabel(self, text="Host:").pack(pady=(10, 0))
        ctk.CTkEntry(self, textvariable=self.host_var).pack()

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(pady=20)
        ctk.CTkButton(btn_frame, text="Cancel", command=self._cancel, width=80).pack(side="right", padx=5)
        ctk.CTkButton(btn_frame, text="OK",     command=self._ok,     width=80).pack(side="right", padx=5)

        self.bind("<Return>", lambda _: self._ok())
        self.bind("<Escape>", lambda _: self._cancel())

        self.result: Dict[str, str] | None = None

    # ---------------------------------------------------------------------
    def _ok(self):
        self.result = {
            "user": self.user_var.get().strip(),
            "pass": self.pass_var.get(),
            "host": self.host_var.get().strip() or "localhost",
        }
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


###############################################################################
# -- main GUI --
###############################################################################

COLOR_MAP = {
    ("JS", "safe"): ("#1e90ff", "#1c86ee"),      # Blue
    ("SQL", "safe"): ("#28a745", "#218838"),     # Green
    ("JS", "danger"): ("#b88a02", "#9c7500"),    # Yellow
    ("SQL", "danger"): ("#dc3545", "#c82333"),   # Red
}


CLUSTER_COMMANDS: List[Dict[str, str]] = [
    # ─────────────────────────  JS / AdminAPI  ──────────────────────────
    # ―― Safe helpers ――
    {
        "title": "Check Cluster Status",
        "template": "dba.getCluster().status({extended:true})",
        "mode": "JS",
        "risk": "safe",
        "hint": "Full topology, lag, errors, etc."
    },
    {
        "title": "List Cluster Instances",
        "template": "dba.getCluster().describe()",
        "mode": "JS",
        "risk": "safe"
    },
    {
        "title": "Rescan Topology",
        "template": "dba.getCluster().rescan()",
        "mode": "JS",
        "risk": "safe"
    },
    {
        "title": "Check Instance Health",
        "template": "dba.checkInstanceConfiguration('<user>@<node>')",
        "mode": "JS",
        "risk": "safe"
    },
    {
        "title": "Check Global Config",
        "template": "dba.checkInstanceConfiguration()",
        "mode": "JS",
        "risk": "safe"
    },
    {
        "title": "Rejoin Instance",
        "template": "dba.getCluster().rejoinInstance('<node>')",
        "mode": "JS",
        "risk": "safe"
    },

    # ―― Higher-risk cluster actions ――
    {
        "title": "Set Primary Instance",
        "template": "dba.getCluster().setPrimaryInstance('<node>')",
        "mode": "JS",
        "risk": "danger",
        "danger": "Triggers failover; brief downtime for writers."
    },
    {
        "title": "Force Rejoin (Clone)",
        "template": "dba.getCluster().rejoinInstance('<node>',{force:true})",
        "mode": "JS",
        "risk": "danger",
        "danger": "May discard transactions on the target."
    },
    {
        "title": "Reboot From Complete Outage",
        "template": "dba.rebootClusterFromCompleteOutage()",
        "mode": "JS",
        "risk": "danger",
        "danger": "Last-resort operation when every node is offline."
    },
    {
        "title": "Add Instance (Clone)",
        "template": "dba.getCluster().addInstance('<user>@<node>',{recoveryMethod:'clone'})",
        "mode": "JS",
        "risk": "danger",
        "danger": "Target must be empty; will wipe existing data."
    },
    {
        "title": "Remove Instance",
        "template": "dba.getCluster().removeInstance('<user>@<node>')",
        "mode": "JS",
        "risk": "danger",
        "danger": "Permanent; instance leaves the replication group."
    },

    # ─────────────────────────────  SQL  ────────────────────────────────
    # ―― Safe diagnostics ――
    {
        "title": "Show Hostname / Port",
        "template": "SELECT @@hostname AS Host, @@port AS Port;",
        "mode": "SQL",
        "risk": "safe"
    },
    {
        "title": "Show Cluster Members",
        "template": "SELECT * FROM performance_schema.replication_group_members;",
        "mode": "SQL",
        "risk": "safe"
    },
    {
        "title": "Show Processlist",
        "template": "SHOW FULL PROCESSLIST;",
        "mode": "SQL",
        "risk": "safe",
        "hint": "Great for spotting long-running or locked queries."
    },
    {
        "title": "Show Engine InnoDB Status",
        "template": "SHOW ENGINE INNODB STATUS\\G",
        "mode": "SQL",
        "risk": "safe",
        "hint": "Deadlocks, semaphores, purge lag, etc."
    },
    {
        "title": "Show Replication Applier Status",
        "template": "SELECT * FROM performance_schema.replication_applier_status;",
        "mode": "SQL",
        "risk": "safe"
    },
    {
        "title": "Show Replication Connection Status",
        "template": "SELECT * FROM performance_schema.replication_connection_status;",
        "mode": "SQL",
        "risk": "safe"
    },
    {
        "title": "Check GTID Mode",
        "template": "SELECT @@gtid_mode;",
        "mode": "SQL",
        "risk": "safe"
    },
    {
        "title": "Check Binlog Format",
        "template": "SELECT @@global.binlog_format;",
        "mode": "SQL",
        "risk": "safe"
    },
    {
        "title": "Check SSL Settings",
        "template": "SHOW VARIABLES LIKE '%ssl_mode%';",
        "mode": "SQL",
        "risk": "safe"
    },
    {
        "title": "Server Version",
        "template": "SELECT VERSION();",
        "mode": "SQL",
        "risk": "safe"
    },

    # ―― Dangerous / writes state ――
    {
        "title": "Set Read-Only Mode",
        "template": "SET GLOBAL super_read_only=ON; SET GLOBAL read_only=ON;",
        "mode": "SQL",
        "risk": "danger",
        "danger": "Stops all writes on this node."
    },
    {
        "title": "Set Read-Write Mode",
        "template": "SET GLOBAL super_read_only=OFF; SET GLOBAL read_only=OFF;",
        "mode": "SQL",
        "risk": "danger"
    },
    {
        "title": "START Group Replication",
        "template": "START GROUP_REPLICATION;",
        "mode": "SQL",
        "risk": "danger"
    },
    {
        "title": "STOP Group Replication",
        "template": "STOP GROUP_REPLICATION;",
        "mode": "SQL",
        "risk": "danger"
    },
    {
        "title": "RESET MASTER (purge binary logs)",
        "template": "RESET MASTER;",
        "mode": "SQL",
        "risk": "danger",
        "danger": "Deletes *all* binlogs; replicas must resync with clone or backup."
    },
]





class ClusterGUI(ctk.CTkFrame):
    def __init__(self, master, mysql_uri: str, creds: Dict[str, str], node_scope: str):
        super().__init__(master)
        self.master = master
        self.mysql_uri = mysql_uri
        self.creds = creds

        self.node_var = ctk.StringVar()
        self.node_leds: Dict[str, ctk.CTkLabel] = {}

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.led_mgr = LEDManager(self)
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.output_q: queue.Queue[str] = queue.Queue()

        # ─── grid layout ────────────────────────────────────────────────
        self.grid_rowconfigure(0, weight=0)   # summary bar
        self.grid_rowconfigure(1, weight=0)   # node / command panels
        self.grid_rowconfigure(2, weight=1)   # terminal (expands)
        self.grid_rowconfigure(3, weight=0)   # input bar
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=1)

        # ─── summary strip ──────────────────────────────────────────────
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=5)
        top_bar.grid_columnconfigure(0, weight=1)

        self.summary_lbl = ctk.CTkLabel(top_bar, text="Loading…", font=("Segoe UI", 14, "bold"))
        self.summary_lbl.grid(row=0, column=0, sticky="w")

        self.refresh_btn = ctk.CTkButton(top_bar, text="Refresh", command=self.refresh_cluster)
        self.refresh_btn.grid(row=0, column=1, sticky="e", padx=(0, 10))

        self.status_led_lbl = ctk.CTkLabel(top_bar, text="")
        self.status_led_lbl.grid(row=0, column=2, sticky="e")

        # ─── node list panel ────────────────────────────────────────────
        self.node_frame = ctk.CTkScrollableFrame(self, width=600, height=265)
        self.node_frame.grid(row=1, column=0, sticky="ew", padx=(10, 5), pady=5)

        self.node_var.trace_add("write", lambda *args: self._update_selected_node_led())

        # ─── command panel ──────────────────────────────────────────────
        self.cmd_grp_scroll = ctk.CTkScrollableFrame(self, width=310, height=265)
        self.cmd_grp_scroll.grid(row=1, column=1, sticky="ew", padx=(5, 10), pady=5)

        ctk.CTkLabel(self.cmd_grp_scroll, text="Cluster Commands",
                     font=("Segoe UI", 14, "bold")).pack(pady=(0, 0))

        self._cmd_btns: List[ctk.CTkButton] = []
        SORT_ORDER = {
            ("JS", "safe"): 0,
            ("SQL", "safe"): 1,
            ("JS", "danger"): 2,
            ("SQL", "danger"): 3,
        }

        for cmd in sorted(
            CLUSTER_COMMANDS,
            key=lambda c: SORT_ORDER.get((c.get("mode", "JS"), c.get("risk", "safe")), 99),
        ):
            mode = cmd.get("mode", "JS")
            risk = cmd.get("risk", "safe")
            fg_color, hover_color = COLOR_MAP.get((mode, risk), ("#444", "#333"))
            button_text = f"⚠️ {cmd['title']}" if risk == "danger" else cmd["title"]

            btn = ctk.CTkButton(
                self.cmd_grp_scroll,
                text=button_text,
                width=260,
                fg_color=fg_color,
                hover_color=hover_color,
                command=lambda c=cmd: self._run_command(c),
            )
            btn.pack(pady=8, anchor="center")
            self._cmd_btns.append(btn)

        # ─── terminal output ────────────────────────────────────────────
        self.output_box = ctk.CTkTextbox(self, font=("Consolas", 12))
        self.output_box.grid(
            row=2, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 10)
        )
        self.output_box.configure(state="disabled", fg_color="black", text_color="lime")

        # ─── custom input bar ───────────────────────────────────────────
        self.input_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.input_frame.grid(
            row=3, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10)
        )
        self.input_frame.grid_columnconfigure(1, weight=1)

        self.mode_var = ctk.StringVar(value="JS")
        self.mode_switch = ctk.CTkSegmentedButton(
            self.input_frame, values=["JS", "SQL"], variable=self.mode_var, width=120
        )
        self.mode_switch.grid(row=0, column=0, sticky="w", padx=(0, 10))

        self.custom_input = ctk.CTkEntry(
            self.input_frame,
            placeholder_text="Enter custom JS/SQL command here...",
        )
        self.custom_input.grid(row=0, column=1, sticky="ew", padx=(0, 10))
        self.custom_input.bind("<Return>", lambda event: self._run_custom_js())

        self.run_custom_btn = ctk.CTkButton(
            self.input_frame, text="Run", command=self._run_custom_js
        )
        self.run_custom_btn.grid(row=0, column=2, sticky="e")

        # initial refresh + log polling
        self.refresh_cluster()
        self._poll_output()

    

    # ------------------------------------------------------------------
    def log(self, text: str):
        self.output_q.put(text)

    def run_mysqlsh(self, js: str) -> str:
        return run_mysqlsh(self.mysql_uri, js)


    def _poll_output(self):
        try:
            while True:
                msg = self.output_q.get_nowait()
                self.output_box.configure(state="normal")
                self.output_box.insert("end", msg + "\n")
                self.output_box.see("end")
                self.output_box.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._poll_output)

    # ------------------------------------------------------------------
    def refresh_cluster(self, silent: bool = False):
        self.led_mgr.set(self.status_led_lbl, "yellowLED.png", blink=True)
        self.summary_lbl.configure(text="Refreshing…")
        self.executor.submit(self._load_cluster_status, silent)


    def _load_cluster_status(self, silent: bool = False):
        try:
            raw = get_cluster_status(self.mysql_uri)
        except RuntimeError as err:
            # Could not talk to mysqlsh  →  log + visual clue
            self.log(f"[ERROR] {err}")
            self.after(0, lambda: self.summary_lbl.configure(
                text="Cluster: N/A  |  Status: connection error"))
            self.after(0, lambda: self.led_mgr.set(
                self.status_led_lbl, "redLED.png", blink=False))
            return
        
        if not silent:
            self.log("Getting cluster status using URI:")

        raw = get_cluster_status(self.mysql_uri)

        if not silent:
            formatted = format_cluster_status(raw)
            self.log(formatted)

        try:
            json_start = raw.find('{')
            json_end = raw.rfind('}') + 1
            cleaned_json = raw[json_start:json_end]
            obj = json.loads(cleaned_json)
        except Exception as e:
            if not silent:
                self.log(f"[ERROR] JSON parse failed: {e}")
            obj = None

        self.after(0, self._apply_cluster_status, obj)




    def _apply_cluster_status(self, obj: Dict[str, Any] | None):
        ok = bool(obj)
        led_img = "greenLED.png" if ok else "redLED.png"
        self.led_mgr.set(self.status_led_lbl, led_img, blink=False)

        if not ok:
            self.summary_lbl.configure(text="Cluster: N/A   Status: error")
            return

        rep = obj.get("defaultReplicaSet", {})
        cluster_name = obj.get("clusterName", "N/A")
        topology_mode = rep.get("topologyMode", "N/A")
        status_text = rep.get("statusText", "N/A")
        self.summary_lbl.configure(
            text=f"Cluster: {cluster_name}  |  Mode: {topology_mode}  |  Status: {status_text}"
        )

        # Clear old node frames
        for child in self.node_frame.winfo_children():
            child.destroy()

        # Add new nodes
        topology = rep.get("topology", {})
        self.node_leds.clear()
        self._node_status_map = {}  # holds status info for later LED update

        for addr, node in topology.items():
            is_primary = node.get("memberRole", "").upper() == "PRIMARY"
            node_card = ctk.CTkFrame(
                master=self.node_frame,
                fg_color="#1a1a1a" if not is_primary else "#1c3d5a",  # default vs. highlight
                border_color="#3399ff" if is_primary else None,
                border_width=2 if is_primary else 0
            )

            node_card.pack(fill="x", padx=10, pady=5)

            top_row = ctk.CTkFrame(master=node_card, fg_color="transparent")
            top_row.pack(fill="x", padx=10)

            # --- LED icon for node status ---
            led_lbl = ctk.CTkLabel(master=top_row, text="")
            self.node_leds[addr] = led_lbl
            self._node_status_map[addr] = node
            led_lbl.pack(side="left", padx=5, pady=5)
            color = get_led_color(node.get("status", ""), node.get("memberRole", ""))
            if is_primary:
                self.led_mgr.set(led_lbl, "blueLED.png", blink=True)
            else:
                self.led_mgr.set(led_lbl, f"{color}LED.png")


            # --- Radio button to select node ---
            rb = ctk.CTkRadioButton(
                master=top_row,
                text=addr,
                variable=self.node_var,
                value=addr,
            )
            rb.pack(side="left", padx=5, pady=5)

            # --- Node details below the selection row ---
            info_text = (
                f"Role: {node.get('memberRole', '?')}  "
                f"Mode: {node.get('mode', '?')}  "
                f"Status: {node.get('status', '?')}\n"
                f"Lag: {node.get('replicationLag', '?')}  "
                f"Ver: {node.get('version', '?')}"
            )

            if node.get("shellConnectError"):
                info_text += f"\nErr: {node['shellConnectError']}"
            if node.get("instanceErrors"):
                for warn in node["instanceErrors"]:
                    info_text += f"\nWarn: {warn}"

            info_label = ctk.CTkLabel(master=node_card, text=info_text, anchor="w", justify="left")
            info_label.pack(fill="x", padx=10, pady=5)

            

        # ------------------------------------------------------------------
    def _update_selected_node_led(self):
        selected = self.node_var.get()
        for node, led_widget in self.node_leds.items():
            status  = self._node_status_map[node]["status"]
            role    = self._node_status_map[node]["memberRole"]
            color   = get_led_color(status, role)
            base_fn = f"{color}LED.png"

            if node == selected:
                # Blink between the node’s own colour and blue
                self.led_mgr.blink_between(led_widget, base_fn, "blueLED.png")
            else:
                # Solid light in the node’s own colour
                self.led_mgr.set(led_widget, base_fn, blink=False)


    # ------------------------------------------------------------------
    def _run_custom_js(self):
        code = self.custom_input.get().strip()
        if not code:
            self.log("[ERROR] No command entered.")
            return

        mode = self.mode_var.get()  # "JS" or "SQL"

        # Basic validation to prevent common mistakes
        if mode == "JS" and code.lower().startswith("select"):
            self.log("[ERROR] Detected SQL syntax, but JS mode is selected. Switch to SQL mode.")
            return
        if mode == "SQL" and not code.strip().endswith(";"):
            self.log("[ERROR] SQL statements should end with a semicolon.")
            return

        self.log(f"[Custom Command - {mode}]\n{code}")
        self.led_mgr.set(self.status_led_lbl, "yellowLED.png", blink=True)

        if mode == "JS":
            # Wrap with print if not already wrapped
            wrapped_code = code if code.startswith("print(") else f"print(JSON.stringify({code}))"
            self.executor.submit(self._exec_command, "Custom JS", wrapped_code)
        else:
            self.executor.submit(self._exec_sql, code)

        self.custom_input.delete(0, "end")




    def _exec_sql(self, sql_code: str):
        env = os.environ.copy()
        env["MYSQLSH_WARN_PASSWORD"] = "0"
    
        result = subprocess.run(
            ["mysqlsh", "--uri", self.mysql_uri, "--sql", "-e", sql_code],
            capture_output=True,
            text=True,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
    
        # Filter insecure password warning from stderr
        stderr_lines = [
            line for line in result.stderr.strip().splitlines()
            if "Using a password on the command line interface can be insecure" not in line
        ]
        stderr_clean = "\n".join(stderr_lines)
    
        if result.stdout.strip():
            pretty = self._beautify_if_json(result.stdout.strip())
            self.log(pretty)

        if stderr_clean:
            self.log(f"[SQL ERROR] {stderr_clean}")
    
        self.custom_input.delete(0, "end")
    



    def _run_command(self, cmd: Dict[str, str]):
        needs_node = "<node>" in cmd["template"]
        node = self.node_var.get()
        if needs_node and not node:
            self.log("[ERROR] Select a node first!")
            return

        # Confirm dangerous commands
        if "danger" in cmd:
            answer = messagebox.askyesno(
                "Confirm Dangerous Action",
                f"Are you sure?\n\n{cmd.get('danger', '')}"
            )
            if not answer:
                return

        tpl = cmd["template"]
        mode = cmd.get("mode", "JS")  # Default to JS if not specified

        # Fill in any placeholders
        filled = (
            tpl.replace("<node>", node)
               .replace("<user>", self.creds["user"])
               .replace("<pass>", self.creds["pass"].replace("'", "\\'"))
               .replace("<user>@<node>", f"{self.creds['user']}@{node}")
        )

        # Define post-action refresh trigger
        def _refresh_after():
            if cmd["title"] == "Set Primary Instance":
                self.after(1000, lambda: self.refresh_cluster(silent=True))

        # Dispatch by mode
        if mode == "SQL":
            self.log(f"[{cmd['title']}]\n{filled}")
            self.led_mgr.set(self.status_led_lbl, "yellowLED.png", blink=True)
            self.executor.submit(self._exec_sql, filled)
            self.after(0, _refresh_after)
        else:
            # JS mode
            if not filled.strip().startswith("print("):
                js_to_run = f"print(JSON.stringify({filled}))"
            else:
                js_to_run = filled

            self.log(f"[{cmd['title']}]\n{filled}")
            self.led_mgr.set(self.status_led_lbl, "yellowLED.png", blink=True)
            self.executor.submit(self._exec_command, cmd["title"], js_to_run)
            self.after(0, _refresh_after)



    def _exec_command(self, title: str, js_to_run: str):
        out = run_mysqlsh(self.mysql_uri, js_to_run)
        if title == "Check Cluster Status":
            try:
                out = format_cluster_status(json.loads(out[out.find("{"):]))
                pretty = self._beautify_if_json(out)
                self.log(pretty)

                if title == "Set Primary Instance":
                    self.after(0, lambda: self.refresh_cluster(silent=False))  # show results in terminal
                else:
                    self.after(0, lambda: self.refresh_cluster(silent=True))   # silent for others
                
            except Exception:
                pretty = self._beautify_if_json(out)
                self.log(pretty)

        else:
            pretty = self._beautify_if_json(out)
            self.log(pretty)


    def _beautify_if_json(self, text: str) -> str:
        try:
            json_start = text.find('{')
            json_end = text.rfind('}') + 1
            json_str = text[json_start:json_end]
            parsed = json.loads(json_str)
            return json.dumps(parsed, indent=2)
        except Exception:
            return text  # Not JSON or can't parse, return original



###############################################################################
# -- script entry point --
###############################################################################

def main():
    root = ctk.CTk()   # hidden root for login dialog
    root.withdraw()

    login = LoginDialog(root)
    root.wait_window(login)
    if not login.result:
        return  # user cancelled

    creds = login.result
    uri = f"{creds['user']}:{creds['pass'].replace('@', '%40')}@{creds['host']}"

    root.destroy()  # close hidden root

    # New main window for tabbed GUI
    app = ctk.CTk()
    app.geometry("1020x915")
    center_window(app, 1020, 915)
    app.title("ClusterDuck")
    
    # Try to load icon if available
    icon_path = IMG / "icon.ico"
    if icon_path.exists():
        try:
            app.iconbitmap(icon_path)
        except Exception:
            pass

    # ─── attempt login / topology fetch ───────────────────────────────
    while True:
        try:
            cluster_json = get_cluster_status(uri)
            nodes = list(json.loads(cluster_json)
                         ['defaultReplicaSet']['topology'].keys())
            break                                   # ← success, exit loop
        except (RuntimeError, json.JSONDecodeError) as err:
            messagebox.showerror(
                "Connect Error",
                f"Could not connect or parse topology:\n\n{err}"
            )
            # show login dialog again
            login = LoginDialog(root)
            root.wait_window(login)
            if not login.result:        # user cancelled
                return
            creds = login.result
            uri = f"{creds['user']}:{creds['pass'].replace('@', '%40')}@{creds['host']}"

    tab_view = ctk.CTkTabview(app, width=1000, height=880)
    tab_view.pack(padx=10, pady=10, fill="both", expand=True)

    for node in nodes:
        tab = tab_view.add(node)
        node_uri = f"{creds['user']}:{creds['pass'].replace('@', '%40')}@{node}"
        gui = ClusterGUI(tab, node_uri, creds, node_scope=node)
        gui.pack(fill="both", expand=True)

    app.mainloop()



if __name__ == "__main__":
    main()
