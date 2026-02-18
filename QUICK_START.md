# JobFinder - Quick Start Guide

## 🚀 How to Run the Application

### Option 1: Double-Click START.bat (Recommended)
Simply double-click `START.bat` in this folder to launch the application.

### Option 2: Use the Terminal
Open PowerShell or Command Prompt in this folder and run:
```bash
python app.py
```

**Note:** On Windows, use `python` (NOT `python3`)

### Option 3: Use the Original run.bat
Double-click `run.bat` in this folder.

---

## ⚠️ Common Issues

### "Python was not found" Error
If you see this error, it means Python is not in your system PATH. You have two options:

#### Quick Fix (No PATH needed)
Use `START.bat` - it automatically finds Python even if it's not in PATH.

#### Permanent Fix (Add Python to PATH)
1. Press `Win + X` and select "System"
2. Click "Advanced system settings"
3. Click "Environment Variables"
4. Under "User variables", find "Path" and click "Edit"
5. Click "New" and add: `C:\Users\darji\AppData\Local\Programs\Python\Python312`
6. Click "New" again and add: `C:\Users\darji\AppData\Local\Programs\Python\Python312\Scripts`
7. Click "OK" on all dialogs
8. **Restart your terminal** for changes to take effect

---

## 📋 First Time Setup

1. **Install Dependencies** (one-time only):
   ```bash
   python -m pip install -r requirements.txt
   ```

2. **Run the Application**:
   - Double-click `START.bat`, OR
   - Run `python app.py` in terminal

3. **Access the Application**:
   - Open your browser to: http://localhost:5000

---

## 🔧 Your Python Installation

- **Location**: `C:\Users\darji\AppData\Local\Programs\Python\Python312\python.exe`
- **Version**: Python 3.12
- **Command to use**: `python` (not `python3`)

---

## 📝 What Each File Does

- **START.bat** - Smart launcher with error handling (recommended)
- **run.bat** - Simple launcher using direct Python path
- **app.py** - Main Flask application
- **requirements.txt** - Python dependencies list

---

## 🆘 Need Help?

If you continue to have issues:
1. Make sure Python 3.12 is installed
2. Try running `START.bat` instead of terminal commands
3. Check that all dependencies are installed: `python -m pip install -r requirements.txt`
