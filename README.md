# ClusterDuck 🐥  
*A Modern GUI for Managing MySQL InnoDB Clusters*

![ClusterDuck Logo](img/duck.webp)

**ClusterDuck** is a modern, dark-themed GUI built with Python and `customtkinter` to manage and monitor [MySQL InnoDB Clusters](https://dev.mysql.com/doc/mysql-shell/8.0/en/). Featuring real-time LED indicators, a tabbed multi-node interface, safe command presets, and portable `.exe` support — it’s the friendliest duck in your database pond.

---

## 🚀 Features

- ✅ Sleek **dark-mode GUI** using `customtkinter`
- ✅ Real-time **LED indicators** (green/yellow/red/blue) for node status
- ✅ **Tabbed layout** for simultaneous multi-node management
- ✅ **Preloaded MySQL Shell commands** (JS + SQL) with color-coded safety levels
- ✅ **Custom JS/SQL input** field with live output display
- ✅ **Safe subprocess handling** (no flashing terminals)
- ✅ **Fully portable `.exe`** (no installer needed)

---

## 🧰 Preinstalled Commands

ClusterDuck includes a wide range of prebuilt administrative and diagnostic commands, color-coded and organized by risk level:

### 🔵 Safe JS Commands
- ✅ Check Cluster Status  
  `dba.getCluster().status({ extended: true })`
- ✅ List Cluster Instances  
  `dba.getCluster().describe()`
- ✅ Rescan Topology  
  `dba.getCluster().rescan()`
- ✅ Check Instance Health  
  `dba.checkInstanceConfiguration('<user>@<node>')`
- ✅ Check Global Config  
  `dba.checkInstanceConfiguration()`

### 🟢 Safe SQL Commands
- ✅ Show Hostname and Port  
  `SELECT @@hostname, @@port;`
- ✅ Show Cluster Members  
  `SELECT * FROM performance_schema.replication_group_members;`
- ✅ Show Replication Applier Status  
  `SELECT * FROM performance_schema.replication_applier_status;`
- ✅ Show Replication Connection Status  
  `SELECT * FROM performance_schema.replication_connection_status;`
- ✅ Check GTID Mode  
  `SELECT @@gtid_mode;`
- ✅ Check Binary Log Format  
  `SELECT @@global.binlog_format;`
- ✅ Check SSL Settings  
  `SHOW VARIABLES LIKE '%ssl_mode%';`
- ✅ MySQL Version  
  `SELECT VERSION();`
- ✅ Set Read-Only Mode  
  `SET GLOBAL super_read_only = ON; SET GLOBAL read_only = ON;`
- ✅ Set Read-Write Mode  
  `SET GLOBAL super_read_only = OFF; SET GLOBAL read_only = OFF;`
- ✅ Start Group Replication  
  `START GROUP_REPLICATION;`

### ⚠️ Dangerous JS Commands (Yellow)
- ⚠️ Set Primary Instance  
  `dba.getCluster().setPrimaryInstance('<node>')`
- ⚠️ Rejoin Instance  
  `dba.getCluster().rejoinInstance('<node>')`
- ⚠️ Force Rejoin  
  `dba.getCluster().rejoinInstance('<node>', {force: true})`
- ⚠️ Reboot from Outage  
  `dba.rebootClusterFromCompleteOutage()`
- ⚠️ Add Instance (Clone)  
  `dba.getCluster().addInstance('<user>@<node>', {recoveryMethod: 'clone'})`
- ⚠️ Remove Instance  
  `dba.getCluster().removeInstance('<user>@<node>')`

### 🟥 Dangerous SQL Commands (Red)
- ⚠️ Stop Group Replication  
  `STOP GROUP_REPLICATION;`

> Dangerous commands are clearly marked in red or yellow with warning icons and hover tooltips in the UI.

---

## 📸 Screenshots

> Add screenshots in the `img/screenshots/` folder and update the links below.

| Login Dialog | Cluster Overview | Node Detail View |
|--------------|------------------|------------------|
| ![Login](img/screenshots/login.png) | ![Overview](img/screenshots/overview.png) | ![Node View](img/screenshots/node-detail.png) |

---

## 📁 Project Structure

InnoDB-Manager/

├── img/

│ ├── icon.png

│ ├── icon.ico

│ ├── greenLED.png

│ ├── yellowLED.png

│ ├── redLED.png

│ ├── blueLED.png

│ └── screenshots/

│ ├── login.png

│ ├── overview.png

│ └── node-detail.png

├── tabbed.py

├── README.md

├── LICENSE

└── dist/

└── ClusterDuck.exe


---

## 🔧 Requirements

- **Python 3.9+** (tested on Python 3.12)
- [`mysqlsh`](https://dev.mysql.com/downloads/shell/) must be installed and available in your system `PATH`
- **Windows 10/11** recommended (but Linux support possible with modification)
- Install required libraries:
  ```bash
  pip install customtkinter pillow psutil

---

## ▶️ Running from Source

```python
python ClusterDuck.py
```

---

## 📦 Build a Standalone .exe

To create a fully portable executable using PyInstaller:

```bash
pyinstaller --noconfirm --onefile --windowed --icon "img/icon.ico" --add-data "img;img/" tabbed.py

```

---

## 🐞 Known Issues

Requires mysqlsh in the system PATH

Designed/tested against MySQL InnoDB Cluster 8.x with GTID enabled

GUI assumes a fully functioning cluster topology with reachable nodes

---

## 📄 License
MIT License

---

## 📬 Feedback & Contributions
Spotted a bug? Have a feature request?

Open an issue or contribute at:
🔗 github.com/wsmaxcy/ClusterDuck