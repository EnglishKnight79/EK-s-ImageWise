# Third-party software in EK's Image Wise

EK's Image Wise is built with the open-source components below. Their licences require that
these notices travel with the app. **Check each project's current licence text before you sell
the app** (the names here are from memory of each project's published licence).

| Component | Used for | Licence (check the project page) |
|---|---|---|
| Qt / PySide6 | the windows and buttons | LGPL v3 (dynamic linking; the Qt libraries ship as separate files in the app so they can be replaced) |
| Pillow | image processing | HPND (permissive) |
| rembg | background removal | MIT |
| ONNX Runtime | runs the background-removal models | MIT |
| U²-Net / IS-Net models | background-removal models | Apache 2.0 |
| NumPy, SciPy, scikit-image, numba, pymatting | support libraries for rembg | BSD-style / MIT-style |
| PyInstaller | packaging only | GPL with an exception for the packaged app |
| Fonts | the Text plugin uses fonts already installed on the computer, or files the user picks | the user's own licences |

Qt for Python (PySide6) is also available under a commercial licence from The Qt Company.
