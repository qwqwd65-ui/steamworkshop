$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $PSCommandPath
$coreScript = Join-Path $scriptDir "download-workshop.ps1"

if (-not (Test-Path $coreScript)) {
    Write-Host "[ERR] 未找到核心脚本: $coreScript" -ForegroundColor Red
    exit 1
}

function Show-Banner {
    Clear-Host
    @'
███████╗ █████╗ ███╗   ██╗    ██╗    ██╗ ██████╗ ██████╗ ██╗  ██╗███████╗██╗  ██╗ ██████╗ ██████╗
██╔════╝██╔══██╗████╗  ██║    ██║    ██║██╔═══██╗██╔══██╗██║ ██╔╝██╔════╝██║  ██║██╔═══██╗██╔══██╗
█████╗  ███████║██╔██╗ ██║    ██║ █╗ ██║██║   ██║██████╔╝█████╔╝ ███████╗███████║██║   ██║██████╔╝
██╔══╝  ██╔══██║██║╚██╗██║    ██║███╗██║██║   ██║██╔══██╗██╔═██╗ ╚════██║██╔══██║██║   ██║██╔═══╝
██║     ██║  ██║██║ ╚████║    ╚███╔███╔╝╚██████╔╝██║  ██║██║  ██╗███████║██║  ██║╚██████╔╝██║
╚═╝     ╚═╝  ╚═╝╚═╝  ╚═══╝     ╚══╝╚══╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝
'@ | Write-Host -ForegroundColor Cyan

    Write-Host ""
    Write-Host "本程序仅用于学习交流，请遵守相关平台规则与法律。" -ForegroundColor Yellow
    Write-Host "---------------------------------------------------"
}

function Run-Core {
    param([string[]]$ArgsList)
    & "C:\Program Files\PowerShell\7\pwsh.exe" -File $coreScript @ArgsList
}

function Get-GameArgs {
    param([string]$InputValue)
    if ($InputValue -match '^\d+$') {
        return @("-AppId", $InputValue)
    }
    return @("-Game", $InputValue)
}

while ($true) {
    Show-Banner
    Write-Host "1. 单条下载"
    Write-Host "2. 单条仅解析直链"
    Write-Host "3. 批量下载（文件一行一个关键词）"
    Write-Host "4. 批量仅解析直链"
    Write-Host "5. 列出支持游戏"
    Write-Host "6. 退出"
    Write-Host ""

    $choice = Read-Host "请输入选项编号"

    switch ($choice) {
        "1" {
            $gameInput = Read-Host "请输入游戏 AppId 或 游戏名（中英文/slug）"
            $kw = Read-Host "请输入关键词"
            $gameArgs = Get-GameArgs -InputValue $gameInput
            Run-Core @($gameArgs + @("-Keyword", $kw))
            Pause
        }
        "2" {
            $gameInput = Read-Host "请输入游戏 AppId 或 游戏名（中英文/slug）"
            $kw = Read-Host "请输入关键词"
            $gameArgs = Get-GameArgs -InputValue $gameInput
            Run-Core @($gameArgs + @("-Keyword", $kw, "-OnlyGetLink"))
            Pause
        }
        "3" {
            $gameInput = Read-Host "请输入游戏 AppId 或 游戏名（中英文/slug）"
            $file = Read-Host "请输入关键词文件路径（每行一个关键词）"
            $gameArgs = Get-GameArgs -InputValue $gameInput
            Run-Core @($gameArgs + @("-ListFile", $file))
            Pause
        }
        "4" {
            $gameInput = Read-Host "请输入游戏 AppId 或 游戏名（中英文/slug）"
            $file = Read-Host "请输入关键词文件路径（每行一个关键词）"
            $gameArgs = Get-GameArgs -InputValue $gameInput
            Run-Core @($gameArgs + @("-ListFile", $file, "-OnlyGetLink"))
            Pause
        }
        "5" {
            Run-Core @("-ListGames")
            Pause
        }
        "6" {
            break
        }
        default {
            Write-Host "无效选项，请重试。" -ForegroundColor Yellow
            Start-Sleep -Seconds 1
        }
    }
}
