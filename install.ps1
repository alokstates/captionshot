# CaptionShot installer for Windows. No admin rights and no Python needed.
#   irm https://raw.githubusercontent.com/alokstates/captionshot/main/install.ps1 | iex
#
# Everything is inside a script block because "iex" runs in the user's own terminal:
# settings stay local, and a failure throws instead of closing their window with "exit".
& {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'   # the progress bar makes downloads far slower on PowerShell 5.1
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    $base = 'https://github.com/alokstates/captionshot/releases/latest/download'
    $file = 'CaptionShot-Setup-windows-x64.exe'
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("captionshot-" + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $tmp | Out-Null

    try {
        $setup = Join-Path $tmp $file
        $sums = Join-Path $tmp 'SHA256SUMS.txt'

        Write-Host 'Downloading CaptionShot...'
        Invoke-WebRequest -UseBasicParsing -Uri "$base/$file" -OutFile $setup
        Invoke-WebRequest -UseBasicParsing -Uri "$base/SHA256SUMS.txt" -OutFile $sums

        Write-Host 'Verifying the download...'
        $want = $null
        foreach ($line in Get-Content $sums) {
            $parts = $line -split '\s+'
            if ($parts.Count -ge 2 -and $parts[1].TrimStart('*') -eq $file) { $want = $parts[0] }
        }
        $got = (Get-FileHash -Algorithm SHA256 -Path $setup).Hash
        if (-not $want -or $want -ine $got) {
            throw "Checksum mismatch for $file. Nothing was installed."
        }

        # Setup cannot replace a running app.
        Get-Process -Name CaptionShot -ErrorAction SilentlyContinue | Stop-Process -Force

        # No /TASKS on purpose: a first install gets the wizard's default options,
        # and an upgrade keeps whatever was chosen before.
        Write-Host 'Installing...'
        $p = Start-Process -FilePath $setup -Wait -PassThru `
            -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CLOSEAPPLICATIONS'
        if ($p.ExitCode -ne 0) { throw "Setup failed with exit code $($p.ExitCode)." }

        $exe = Join-Path $env:LOCALAPPDATA 'Programs\CaptionShot\CaptionShot.exe'
        if (-not (Test-Path $exe)) { throw "Setup finished but $exe is missing." }
        Start-Process -FilePath $exe

        Write-Host ''
        Write-Host 'CaptionShot is installed and running in your system tray.'
        Write-Host '  Take a screenshot:  Print Screen'
        Write-Host '  Starts at sign-in:  yes (change this in the app''s settings)'
        Write-Host '  Uninstall:          Settings > Apps > CaptionShot'
        Write-Host ''
    }
    finally {
        Remove-Item -Recurse -Force -Path $tmp -ErrorAction SilentlyContinue
    }
}
