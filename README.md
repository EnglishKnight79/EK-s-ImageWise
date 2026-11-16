# EK's Image Wise

Load an image, crop it, resize it, and (with the built-in plugins) remove the background, add alpha overlays,
preview the result, export it.

## Your splash screen and icon

Put two files in the project folder, next to `main.py` (the names must match exactly):

* `Icon_1.png` - the app icon (taskbar on Windows, Dock on Mac, window corner). Use a square PNG with a
  transparent background, 512 x 512 or bigger. The installers' icons are made from it automatically.
* `splash.png` - the splash screen shown while the app starts (about 900 pixels wide works well; wider
  pictures are scaled down). It stays on screen for at least a moment so it can be seen.

If either file is missing the app simply uses its built-in icon / starts without a splash. The installers
include both files.

## Installers (Windows and Mac)

To make a proper installer for Windows or a `.dmg` for Mac, read **packaging/PACKAGING.md**.
Short version: push the project to GitHub and run the "Build installers" workflow (it builds the
Windows setup file and both Mac disk images), or double-click `packaging/build_windows.bat` on a PC /
run `./packaging/build_mac.sh` on a Mac.

## Run it from source (Windows or Mac)

1. Install Python 3.10 or newer (python.org). On Windows tick "Add Python to PATH".
2. Open a terminal in this folder and run:

       python -m venv venv
       venv\Scripts\activate          (Windows)
       source venv/bin/activate       (Mac)
       pip install -r requirements.txt
       python main.py

## How to use

- File > Open (or drag an image onto the window). Open starts a new job; the alphas,
  canvas colour and DPI you had are kept for the next client image (plugins keep their own settings).
- **Undo / Redo**: the red and green buttons top left (Ctrl+Z, Ctrl+Y or Ctrl+Shift+Z).
  Every setting is covered: crop, photos, placement, cut-outs, canvas, pattern,
  overlays, plugin settings. A slider drag counts as one step.
- **Settings panel**: the sidebar is a dock. Drag its title bar to float it as its own window
  (handy on a second screen), double-click the title to float / re-dock, or drag it to the left
  side. View > Settings panel brings it back if you close it. It always fits its width, so
  Lock and Reset are never off-screen, and it remembers where you left it.
- **Light and dark theme**: View > Theme switches the whole app (and the preview background) between
  Light and Dark. It is remembered for next time.
- **Close all**: the button above the settings panel minimises every category in one click.
- **Sidebar categories**: each category (Photos, Crop, Canvas size, and one per plugin: Alpha Overlays,
  Background Removal, Colour & Brightness, Crop Shapes, Filters, Pattern / Poster, Text) starts minimised; click its title to open it.
  **Reset** puts just that category back to its defaults (Undo brings it back).
  **Lock** greys the category out, and stops it being changed by dragging in the previews too.
- **Mouse wheel safety**: the wheel only changes a slider / box after you have clicked it;
  until then it just scrolls the sidebar.
- **Crop pane** (left): drag on the image to draw a crop box, or type exact pixel values.
- **Preview pane** (right): shows the final result live, next to the crop pane. The
  Crop / Preview buttons above hide or show each pane.
- **Zoom** either pane: mouse wheel (towards the cursor) or the - + Fit 1:1 buttons.
  Move the view with middle-button or right-button drag, or Alt + left drag.
  When you zoom the preview in, it re-renders the visible part sharply.
- Resize: set width/height in pixels (aspect lock on by default) and DPI.
  The "Print size" line shows the physical size at that DPI.
- Export (Ctrl+E): PNG, JPEG, TIFF or WebP. The DPI is written into the file.

- **Composition (several photos on one print)**: open the first picture, then use
  File > Add photo to composition (or **Add photo...** in the Photos box, or drop more
  files onto the window). Each photo is its own layer: click it in the Preview to select it,
  drag to move, drag the yellow corner handle (or Shift + wheel) to resize, and use the
  Rotate / Opacity sliders. Up / Down change the layer order. The **Crop** and
  **Background removal** categories act on the selected photo, so every photo can have
  its own crop and cut-out. "Fill canvas" stretches a photo over the whole canvas (the
  default for the first photo); untick it to place the photo freely. Set the print size
  (pixels or cm) and a canvas colour in **Canvas size / output**. In a pattern, every
  visible photo is mixed into the repeat.
- **Crop shapes** (the *Crop Shapes* plugin): crop the selected photo to a shape taken from a folder of
  shape pictures. Type or browse to the folder in the plugin's category (the default is
  `<home>/EKImageWise/shapes`; sub-folders are included) and click a shape in the picture list. A shape
  picture can be a PNG / WebP / TIFF with transparency (the visible part is the shape), or a plain
  picture with a dark shape on a light background or the other way round (use *Invert shape* if the
  guess is wrong). The shape fits inside the crop box and scales with it (resize the box in the Crop
  pane, or use *Shape size*), and can be **rotated** with the Rotate slider; everything outside the shape
  is transparent. Optional outline with colour and width. Shapes work on every photo in a composition
  and in patterns. The app comes with no shapes: add your own. Switching the plugin off, or deleting
  `plugins/crop_shapes.py`, removes crop shapes from the app.
- **Canvas background**: in Canvas size / output choose Transparent, a Solid colour, or a
  two-colour **Gradient** (any angle, or radial from the centre).
- **Plugins**: nearly every feature beyond cropping, resizing and composing is a plugin, each with its own
  category in the sidebar, a tick to switch it on or off, and its own Reset and Lock. Delete a plugin's
  file from the `plugins` folder and that feature is gone from the app. The built-in ones:
  * **Background Removal** - cuts the subject out of the selected photo with an AI model (first run
    downloads the model unless it was bundled in the installer). *Show cut-out* toggles it, *Edge shrink*
    and *Feather* tidy the edge instantly. Every photo can have its own cut-out.
  * **Alpha Overlays** - up to four alpha pictures from your own folder on top of everything
    ("Choose alpha folder..." once, it is remembered). Pick one from a layer's drop-down, then in Preview
    drag it to move, drag the corner handle or Shift + wheel to resize; Size, Opacity, Visible, Centre
    and Up / Down (layer order) are in the layer's box. They keep their place for the next image.
  * **Pattern / Poster** - tick "Tile the image as a pattern" to repeat the photos across a poster-size
    canvas: poster and tile size in cm, gap, stagger (brick / half-drop), random rotation (Shuffle for a
    new arrangement), background colour or transparency. "Seamless repeat" adjusts the spacing so the
    poster repeats perfectly side by side. While it is on, the Canvas size controls are greyed out
    (the poster size sets the canvas) and photos can't be dragged (they are the tiles).
  * **Crop Shapes** - see above.
  * **Colour & Brightness** - brightness, contrast and saturation sliders.
  * **Filters** - black & white, sepia, invert, blur, sharpen, vignette, posterize, solarize, emboss, line
    drawing, pixelate, film grain, hue shift, warm/cool tint, duotone, gradient map and gradient overlay
    (colours, angle, radial, blend mode, opacity); tick the ones you want.
  * **Text** - several text boxes with any installed font (or a font file), size in cm, bold / italic /
    underline / strike-through, colour, alignment, line and letter spacing, position, rotation, opacity,
    outline (colour and width) and drop shadow (colour, offset, blur, opacity).
  See `plugins/README.md` and `plugins/_template.py` to write your own.

The original image is never changed; edits are stored as settings and applied
at export time (non-destructive).

## Project layout

    main.py                      entry point
    imagewise/engine/document.py edits + rendering + export (no UI code)
    imagewise/engine/background.py  applies a photo's cut-out mask + edge refinement (the AI is in the plugin)
    imagewise/engine/blend.py       small image-blending helpers
    imagewise/engine/effects.py     hook that lets plugins change the picture
    imagewise/plugins/              plugin API (api.py) and loader (loader.py)
    imagewise/ui/plugin_manager.py  sidebar boxes + plugin manager dialog
    imagewise/engine/photo.py       one picture in the composition (crop, cut-out, placement)
    imagewise/engine/history.py     undo / redo history
    imagewise/ui/photos_panel.py    the Photos category
    imagewise/ui/category_box.py    collapsible category with Lock and Reset
    imagewise/ui/wheel_guard.py     click-before-scroll protection
    imagewise/engine/shapes.py      crop shapes (loaded from picture files)
    imagewise/engine/gradient.py    colour gradients
    plugins/*.py                    the built-in plugins: alpha_overlays, background_removal, colour_brightness,
                                    crop_shapes, filters, pattern_poster, text_tool
    main.py, splash.png, Icon_1.png  start-up file, splash screen and taskbar icon (see below)
    plugins/                        built-in plugins and the plugin template
    imagewise/ui/canvas.py       image display + crop dragging
    imagewise/ui/main_window.py  window, controls, wiring


