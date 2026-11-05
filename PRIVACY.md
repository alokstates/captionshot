# Privacy Policy

**Effective:** 5 November 2026

CaptionShot is a free, open-source app that runs on your computer. It has no accounts, no analytics and no ads.
The project does not run a server, so the project never receives your screenshots, captions or settings.

## What stays on your computer

| Data | Where it goes |
|---|---|
| Screenshots | Your chosen save folder (by default `Pictures/CaptionShot`), only when you save them |
| Copied images | Your system clipboard, when you choose copy |
| Settings | `%APPDATA%\CaptionShot` on Windows, `~/.config/CaptionShot` on macOS |
| Hindi words you have picked | `hindi_words.json` in the same settings folder |

If your save folder is synced by a service such as OneDrive or iCloud, that service will receive your saved
screenshots under its own terms. The same applies to your clipboard if you use clipboard sync.

## The one thing sent over the internet: Hindi typing

Hindi typing is off until you turn it on. While it is on, each word in your caption is sent to Google's Input
Tools service (`inputtools.google.com`) as you type it, to get Hindi spelling suggestions. Google receives the
word and, as with any internet request, your IP address. Your screenshots are never sent.

The project has no control over how Google handles this data. See
[Google's Privacy Policy](https://policies.google.com/privacy).

To avoid this, leave Hindi typing off. If your computer is offline, the app uses its built-in suggestions instead.

## What your screenshots can reveal

The caption bar's stamp is on by default. It adds the date, the time and **the title of the active window** to the
image, and window titles can include things like document names or email subjects. Check the stamp before sharing
a screenshot, or turn it off in the app's settings. Saved file names can also include your caption text.

## System permissions

- **macOS:** Screen Recording permission is needed to capture the screen. You can turn it off at any time in
  System Settings.
- **Windows:** the installer can set the app to start when you sign in, and can make the Print Screen key open it.
  It changes these settings only for your user account.

## Downloads and GitHub

The app and its install commands are hosted on GitHub. When you download them, or visit or contribute to the
project on GitHub, [GitHub's Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement)
applies. Anything you post in a public issue can be seen by everyone, so check screenshots before attaching them.

## Your choices

You stay in control of your data because it is stored on your computer. To remove it, delete your saved
screenshots and the settings folder listed above. See [Uninstall](README.md#uninstall).

## Children

CaptionShot does not knowingly collect personal information from anyone, including children.

## Changes

Changes to this policy are published in this file, and the [file's history](https://github.com/alokstates/captionshot/commits/main/PRIVACY.md)
shows every earlier version.

## Contact

Questions are welcome in [GitHub Issues](https://github.com/alokstates/captionshot/issues).
