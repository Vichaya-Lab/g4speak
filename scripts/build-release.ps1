param([string]$Compiler = '')
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
if (-not $Compiler) {
    $Compiler = & (Join-Path $PSScriptRoot 'install-inno.ps1')
}
python -m unittest discover -s tests -p 'test_*.py'
if ($LASTEXITCODE -ne 0) { throw 'Regression tests failed.' }
python -m PyInstaller --noconfirm packaging/windows/G4Speak.spec
if ($LASTEXITCODE -ne 0) { throw 'Application build failed.' }
$version = (Get-Item -LiteralPath 'dist\G4Speak.exe').VersionInfo.ProductVersion
if (-not $version) { throw 'Application version metadata is missing.' }
if ($env:GITHUB_REF_TYPE -eq 'tag' -and $env:GITHUB_REF_NAME -ne "v$version") {
    throw "Release tag $env:GITHUB_REF_NAME does not match application version $version."
}
& $Compiler '/Qp' (Join-Path $PSScriptRoot '..\packaging\windows\installer.iss')
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
$installer = "dist\G4Speak-Setup-$version.exe"
if (-not (Test-Path -LiteralPath $installer)) { throw 'Installer version does not match the application.' }
$checksums = @('dist\G4Speak.exe', $installer) | ForEach-Object {
    $hash = (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash  $([IO.Path]::GetFileName($_))"
}
$checksums | Set-Content -LiteralPath 'dist\SHA256SUMS.txt' -Encoding ascii
Write-Output "Built $installer and dist\G4Speak.exe"
