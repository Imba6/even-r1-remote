import sys
import subprocess

def startup_enabled():
    if sys.platform != "win32": return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            winreg.QueryValueEx(key, "EvenR1Remote")
            return True
    except FileNotFoundError:
        return False

def set_startup(enabled):
    import winreg
    args = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "even_r1"]
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
        if enabled: winreg.SetValueEx(key, "EvenR1Remote", 0, winreg.REG_SZ, subprocess.list2cmdline(args))
        else:
            try: winreg.DeleteValue(key, "EvenR1Remote")
            except FileNotFoundError: pass
