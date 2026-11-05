# Contributing to CaptionShot

Thanks for helping out. Bug reports, ideas and code are all welcome.

## Reporting a bug

[Open an issue](https://github.com/alokstates/captionshot/issues/new) and include:

- Your operating system and CaptionShot version
- What you did, what you expected, and what happened

Public issues can be seen by everyone, so check any screenshots for private information before attaching them.

## Changing the code

1. Fork the repo and create a branch.
2. Run the app from source (Python 3.10 to 3.15):

   ```bash
   python -m pip install -r packaging/requirements-build.txt
   python captionshot.py
   ```

3. Test your change on the platforms it affects. If you can only test on one, say so in your pull request.
4. Run the packaged build's self-test with `build.bat` on Windows or `./build.sh` on macOS.
5. Open a pull request saying what changed and why. GitHub builds and self-tests it on Windows and macOS.

The app is a single file, `captionshot.py`. Please keep changes focused, and open an issue first for anything large.

## Licence

By submitting a contribution, you agree that it is released under the project's [MIT License](LICENSE), and that
you have the right to submit it.
