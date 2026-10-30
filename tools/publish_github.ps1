# Publish Renewal Radar to GitHub.
# 1) Create an EMPTY repository on github.com (no README), e.g. renewal-radar
# 2) Run:  powershell -ExecutionPolicy Bypass -File tools\publish_github.ps1 https://github.com/<you>/renewal-radar.git
param([Parameter(Mandatory=$true)][string]$RepoUrl)
Set-Location (Split-Path $PSScriptRoot -Parent)
git remote remove origin 2>$null
git remote add origin $RepoUrl
git branch -M main
git push -u origin main
