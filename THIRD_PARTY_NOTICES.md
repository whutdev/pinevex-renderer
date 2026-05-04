# Third-party notices

Pinevex-authored source code in this repository is licensed under the Apache License, Version 2.0. Third-party components included in the repository retain their original licenses.

This notice is not a replacement for the upstream license texts. If you redistribute this repository, keep this file and preserve upstream copyright/license notices.

## Vendored native libraries

`vendor/native/` contains Linux shared libraries used by hosted/serverless rendering:

- `libEGL.so.1`
- `libGL.so.1`
- `libGLX.so.0`
- `libGLdispatch.so.0`
- `libX11.so.6`
- `libXau.so.6`
- `libXdmcp.so.6`
- `libXext.so.6`
- `libexpat.so.1`
- `libxcb.so.1`

These are third-party runtime libraries from Mesa/libglvnd, X.Org/XCB, and Expat-family system packages. They are not relicensed by Pinevex Renderer.

## Vendored fonts

`src/ui_engine/fonts/` contains bundled typefaces used so render output is stable across local and serverless environments.

The bundled font families include fonts distributed under licenses such as the SIL Open Font License 1.1, Apache License 2.0, and Ubuntu Font License 1.0. `TwemojiMozilla.ttf` is from Mozilla's [`twemoji-colr`](https://github.com/mozilla/twemoji-colr) package; its code is Apache License 2.0 and its Twemoji visual artwork is redistributed under CC BY 4.0. The generated `RobloxEmoji.ttf` compatibility font is included for Roblox private-use glyph rendering and is not a Roblox endorsement or trademark grant.

Font files are not relicensed by Pinevex Renderer. Preserve their embedded copyright and license metadata when redistributing this repository.

## Runtime dependencies

Python dependencies installed from `requirements.txt` are not vendored. Their package metadata and upstream repositories define their license terms.
