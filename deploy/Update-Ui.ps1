param([string]$ServerHost='8.163.121.238',[int]$Port=22,[string]$IdentityFile)
$ErrorActionPreference='Stop'
if($ServerHost -ne '8.163.121.238'){throw 'This updater targets the existing inspected installation only.'}
$project=Split-Path $PSScriptRoot -Parent
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$archive=Join-Path $env:TEMP "private-hub-ui-$stamp.zip"
$tool=Join-Path $PSScriptRoot 'archive-tool.py'
& python $tool pack $project $archive
if($LASTEXITCODE -ne 0){throw 'Archive validation failed.'}
$ssh=Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
$scp=Join-Path $env:WINDIR 'System32\OpenSSH\scp.exe'
$scpArgs=@('-P',"$Port",'-o','StrictHostKeyChecking=ask','-o','ConnectTimeout=15')
$sshArgs=@('-t','-p',"$Port",'-o','StrictHostKeyChecking=ask','-o','ConnectTimeout=15')
if($IdentityFile){$scpArgs+=@('-i',$IdentityFile);$sshArgs+=@('-i',$IdentityFile)}
Write-Host 'Updates web assets and folder APIs, with a server-side backup. Password/data/HTTPS config are not changed.'
Write-Host 'Application changes restart private-hub, clearing existing login sessions and briefly disconnecting relay clients.'
if((Read-Host 'Type UPDATE to upload and apply') -cne 'UPDATE'){return}
& $scp @scpArgs $archive $tool "root@${ServerHost}:/root/"
if($LASTEXITCODE -ne 0){throw 'Upload failed. No remote update attempted.'}
$archiveName=Split-Path $archive -Leaf
$remote="/root/private-hub-ui-$stamp"
$command="umask 077; python3 /root/archive-tool.py unpack '/root/$archiveName' '$remote' && python3 '$remote/deploy/update-ui.py'"
& $ssh @sshArgs "root@$ServerHost" $command
if($LASTEXITCODE -ne 0){throw 'Remote update failed. Review terminal output; do not share passwords.'}
Write-Host 'Update complete. Refresh the browser and log in again if prompted.'
