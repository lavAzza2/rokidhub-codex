## RokidHub Desktop Connector 0.6.0-beta.7

This update fixes reopening the Connector after it has been closed to the
Windows notification area.

### Fixed

- A click or double-click on the tray icon reliably restores and activates the
  hidden Connector window.
- The tray menu marks **Open** as its default action.
- Starting RokidHub Desktop Connector again from the Start menu, desktop
  shortcut, or executable now opens the already running window instead of
  silently exiting.

The Connector service still runs separately in the background while the GUI is
hidden. This is expected and does not create a second tray application.
