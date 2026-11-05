# Copyright and third-party notices

CaptionShot is Copyright (c) 2026 alokstates and is released under the [MIT License](LICENSE).

The MIT License covers CaptionShot's own code. The installed app also includes the components below, which stay
under their own licences.

| Component | Used for | Copyright | Licence |
|---|---|---|---|
| [Qt 6](https://www.qt.io/) | Windows, drawing, networking | The Qt Company Ltd. and contributors | LGPL-3.0 |
| [PySide6 and Shiboken6](https://doc.qt.io/qtforpython-6/) | Using Qt from Python | The Qt Company Ltd. | LGPL-3.0 |
| [Python](https://www.python.org/) | Runs the app | Python Software Foundation | PSF License |
| [Mukta fonts](https://github.com/EkType/Mukta) | Hindi text | Girish Dalvi, Ek Type | SIL Open Font License 1.1 |
| [PyInstaller](https://pyinstaller.org/) bootloader | Starts the packaged app | PyInstaller Development Team | GPL-2.0-or-later with an exception that allows distributing built apps under any licence |

The licence texts are in the [`licenses`](licenses) folder, and the Mukta licence is at
[`fonts/OFL.txt`](fonts/OFL.txt). They are also included with the installed app.

## Qt and PySide6 (LGPL-3.0)

The app uses Qt 6.12 and PySide6 6.12 without modifying them. They are kept as separate library files in the
install folder, so you can replace them with your own compatible versions. You can get their source code from
[code.qt.io](https://code.qt.io/) and rebuild CaptionShot with your changes using the
[build steps in the README](README.md#run-or-build-from-source).

## Trademarks

Windows, macOS, Google and other product names belong to their owners. CaptionShot is an independent project and
is not affiliated with or endorsed by them.
