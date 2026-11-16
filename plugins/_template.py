"""Starting point for your own plugin.

This file's name starts with an underscore, so the app ignores it. Copy it,
rename the copy (for example my_plugin.py) and edit. Put it in:
  - the "plugins" folder next to the app, or
  - your personal folder:  <home>/EKImageWise/plugins
then use  Plugins > Reload plugins  in the app.
"""
from PIL import ImageOps

from imagewise.plugins.api import Plugin


class MyPlugin(Plugin):
    name = "My plugin"
    version = "1.0"
    author = "Your name"
    description = "Turns the picture black and white."

    def apply(self, image, ctx):
        # Must return an image of the SAME size. ctx.scale = output scale (1.0 = full size),
        # ctx.preview = True on screen, False for the final export.
        alpha = image.getchannel("A") if image.mode == "RGBA" else None
        out = ImageOps.grayscale(image).convert("RGB")
        if alpha is not None:
            out.putalpha(alpha)
        return out

    # Optional: add controls to the sidebar.
    # def create_panel(self):
    #     from PySide6.QtWidgets import QCheckBox
    #     box = QCheckBox("Something")
    #     box.toggled.connect(lambda on: self.host.request_refresh())   # redraw after a change
    #     return box


PLUGIN = MyPlugin
