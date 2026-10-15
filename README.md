# Purel
Simple automation scripts for downloading and running mining software in the background on a VPS or container.

## Features
* ⚡ One-command installation and execution
* 🔄 Automatically downloads the latest version
* 🎲 Random worker name generated on every run (6 chars, lowercase)
* 🚀 Probes Kryptex pools and picks the lowest-latency region automatically
* 🖥️ Designed for VPS / container environments
* 🔕 Runs in the background using `nohup`


## Installation

### 1. Login to your VPS
```bash
ssh root@IP_VPS
```

### 2. Clone & Run
- [SRBMiner-MULTI](https://github.com/doktor83/SRBMiner-Multi)
```bash
git clone https://github.com/petrixbot/purel.git /root/learning && cd /root/learning && nohup python3 srblearn.py > logger.log 2>&1 &
```
- [PeakMiner](https://github.com/peakminer/peakminer/)
```bash
git clone https://github.com/petrixbot/purel.git /root/learning && cd /root/learning && nohup python3 peaklearn.py > logger.log 2>&1 &
```

## Monitoring
View the running logs:
```bash
tail -f /root/learning/logger.log
```

Check the running process:
```bash
ps aux | grep -E "peaklearn|srblearn|python3"
```

Stop the process:
```bash
pkill -f "peaklearn.py"
```
or:
```bash
pkill -f "srblearn.py"
```

## License
This project is licensed under the [MIT License](https://choosealicense.com/licenses/mit/).
