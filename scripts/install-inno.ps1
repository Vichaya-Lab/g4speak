param([string]$Destination = (Join-Path $PSScriptRoot '..\build\tools\InnoSetup'))
$ErrorActionPreference = 'Stop'
$Destination = [IO.Path]::GetFullPath($Destination)
$compiler = Join-Path $Destination 'ISCC.exe'
if (Test-Path -LiteralPath $compiler) { Write-Output $compiler; exit 0 }
$toolsDirectory = Split-Path -Parent $Destination
New-Item -ItemType Directory -Path $toolsDirectory -Force | Out-Null
$download = Join-Path $toolsDirectory 'innosetup-6.7.3.exe'
Invoke-WebRequest -Uri 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe' -OutFile $download
$signature = Get-AuthenticodeSignature -LiteralPath $download
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Pyrsys B.V.') {
    throw 'The Inno Setup download did not pass publisher signature verification.'
}
$arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', '/NOICONS', ('/DIR="' + $Destination + '"'))
$process = Start-Process -FilePath $download -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $compiler)) {
    throw "Inno Setup installation failed with exit code $($process.ExitCode)."
}
Write-Output $compiler
