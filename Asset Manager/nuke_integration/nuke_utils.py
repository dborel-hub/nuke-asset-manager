"""
Nuke-specific utilities
"""


def get_nuke_main_window():
    """
    Get Nuke's main window QWidget
    
    Returns:
        QMainWindow or None
    """
    try:
        from PySide2 import QtWidgets
    except ImportError:
        try:
            from PySide6 import QtWidgets
        except ImportError:
            return None
    
    app = QtWidgets.QApplication.instance()
    if app:
        for widget in app.topLevelWidgets():
            if widget.objectName() == 'NukeMainWindow' or 'Nuke' in widget.windowTitle():
                return widget
    
    return None


def get_nuke_version():
    """Get Nuke version"""
    try:
        import nuke
        return nuke.NUKE_VERSION_STRING
    except:
        return "Unknown"


def is_nuke_indie():
    """Check if running in Nuke Indie"""
    try:
        import nuke
        return 'Indie' in nuke.NUKE_VERSION_STRING or nuke.env.get('indie', False)
    except:
        return False
