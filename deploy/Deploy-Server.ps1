param([string]$ServerHost='8.163.121.238',[int]$Port=22,[string]$IdentityFile,[switch]$Diagnostic,[switch]$LegacyScp,[switch]$SetupHttps)
$ErrorActionPreference='Stop'
if($ServerHost -ne '8.163.121.238'){throw 'Installer is restricted to the inspected server 8.163.121.238'}
$project=Split-Path $PSScriptRoot -Parent
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$archive=Join-Path $env:TEMP "private-hub-$stamp.zip"
$remote="/root/private-hub-upload-$stamp"
$ssh=Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
$scp=Join-Path $env:WINDIR 'System32\OpenSSH\scp.exe'
$archiveTool=Join-Path $PSScriptRoot 'archive-tool.py'
& python $archiveTool pack $project $archive
if($LASTEXITCODE -ne 0){throw 'Local archive verification failed. Nothing uploaded.'}
$scpArgs=@('-P',"$Port",'-o','StrictHostKeyChecking=ask','-o','ConnectTimeout=15')
$sshArgs=@('-t','-p',"$Port",'-o','StrictHostKeyChecking=ask','-o','ConnectTimeout=15')
if($IdentityFile){$scpArgs+=@('-i',$IdentityFile);$sshArgs+=@('-i',$IdentityFile)}
if($Diagnostic){$scpArgs+= '-v';$sshArgs+= '-v'}
if($LegacyScp){$scpArgs+= '-O'}
Write-Host 'Upload code only. No local database, private keys, or passwords are included.'
Write-Host 'SSH may ask for the server password twice: once to upload, once to install.'
& $scp @scpArgs $archive $archiveTool "root@${ServerHost}:/root/"
if($LASTEXITCODE -ne 0){
    Write-Warning 'Upload connection failed. No installation attempted; no automatic password retries.'
    Write-Warning 'Check ordinary SSH login first. Use -Diagnostic for SSH transport details; use -LegacyScp only if SSH works but the SFTP subsystem fails.'
    throw 'Upload failed. No installation attempted.'
}
Write-Host 'Next: private backup, backend installation, NEW Hub admin password prompt, certificate validation.'
Write-Host 'Public site switches only if TLS validates and you type DEPLOY. Existing BaoTa nginx is reused.'
# No embedded double quotes: compatible with Windows PowerShell 5.1 native argument passing.
$archiveName=Split-Path $archive -Leaf
$command="umask 077; python3 /root/archive-tool.py unpack '/root/$archiveName' '$remote' && python3 '$remote/deploy/install-server.py'"
if($SetupHttps){
    Write-Host 'HTTPS setup: free Lets Encrypt IP certificate, CA terms confirmation, automated renewal every 6 hours.'
    $command+=' --setup-https'
}
& $ssh @sshArgs "root@$ServerHost" $command
$code=$LASTEXITCODE
if($code -eq 20){Write-Warning 'Backend installed, but trusted HTTPS failed. Public website was NOT switched. Send the certificate diagnostics for the next step.'}
elseif($code -ne 0){Write-Warning "Remote installation stopped with exit code $code. Send the output, but no secrets."}
exit $code
