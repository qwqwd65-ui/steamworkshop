param(
    [string]$Game,
    [int]$AppId,
    [string]$Keyword,
    [string]$ListFile,
    [string]$OutDir = ".\downloads",
    [switch]$OnlyGetLink,
    [switch]$ListGames,
    [switch]$RefreshGamesCache,
    [int]$Limit = 0
)

$ErrorActionPreference = "Stop"
$catalogBase = "https://catalogue.smods.ru"
$homeUrl = "$catalogBase/"
$scriptDir = Split-Path -Parent $PSCommandPath
$configPath = Join-Path $scriptDir "config.json"
$gamesCachePath = Join-Path $scriptDir "games-cache.json"

function Write-Step {
    param([string]$Message)
    Write-Host "[STEP] $Message" -ForegroundColor Cyan
}

function Write-WarnLine {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Find-FirstMatch {
    param(
        [string]$Text,
        [string[]]$Patterns
    )
    foreach ($pattern in $Patterns) {
        $m = [regex]::Match($Text, $pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
        if ($m.Success) { return $m.Groups[1].Value }
    }
    return $null
}

function Html-Decode {
    param([string]$Text)
    if ($null -eq $Text) { return $null }
    return [System.Net.WebUtility]::HtmlDecode($Text)
}

function Decode-Slug {
    param([string]$Slug)
    if ([string]::IsNullOrWhiteSpace($Slug)) { return $Slug }
    try {
        return [System.Uri]::UnescapeDataString($Slug)
    }
    catch {
        return $Slug
    }
}

function New-CommonHeaders {
    return @{
        "User-Agent" = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        "Accept-Language" = "en-US,en;q=0.9"
    }
}

function Normalize-Name {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return "" }
    $t = $Text.Trim().ToLowerInvariant()
    $t = ($t -replace '%[0-9a-f]{2}', ' ')
    $t = ($t -replace '[^0-9a-z\u4e00-\u9fff]+', '')
    return $t
}

function Get-NameVariants {
    param(
        [string]$GameName,
        [string]$Slug
    )

    $set = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)

    if (-not [string]::IsNullOrWhiteSpace($GameName)) {
        [void]$set.Add($GameName.Trim())

        foreach ($m in [regex]::Matches($GameName, '[\u4e00-\u9fff]{2,}')) {
            [void]$set.Add($m.Value)
        }

        foreach ($m in [regex]::Matches($GameName, '[A-Za-z0-9][A-Za-z0-9 ''&:;,+\-.]{2,}')) {
            $v = $m.Value.Trim()
            if ($v.Length -ge 3) { [void]$set.Add($v) }
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($Slug)) {
        [void]$set.Add($Slug)
        $decodedSlug = [System.Uri]::UnescapeDataString($Slug)
        [void]$set.Add($decodedSlug)
        [void]$set.Add(($decodedSlug -replace '-', ' '))
    }

    return @($set)
}

function Load-Config {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        Write-Host "[INFO] 首次运行程序，跳过配置检查..." -ForegroundColor Yellow
        return $null
    }

    try {
        $raw = Get-Content -Raw $Path
        if ([string]::IsNullOrWhiteSpace($raw)) {
            Write-WarnLine "配置文件为空，已使用命令行参数。"
            return $null
        }
        return ($raw | ConvertFrom-Json)
    }
    catch {
        Write-WarnLine "配置文件解析失败，已使用命令行参数。"
        return $null
    }
}

function Get-Web {
    param(
        [string]$Uri,
        [hashtable]$Headers,
        [Microsoft.PowerShell.Commands.WebRequestSession]$Session
    )
    return Invoke-WebRequest -Uri $Uri -Headers $Headers -WebSession $Session -UseBasicParsing
}

function Post-Web {
    param(
        [string]$Uri,
        [hashtable]$Headers,
        [hashtable]$Body,
        [Microsoft.PowerShell.Commands.WebRequestSession]$Session
    )
    return Invoke-WebRequest -Uri $Uri -Method Post -Headers $Headers -Body $Body -WebSession $Session -UseBasicParsing
}

function Get-SupportedGames {
    param([Microsoft.PowerShell.Commands.WebRequestSession]$Session)

    $html = (Get-Web -Uri $homeUrl -Headers (New-CommonHeaders) -Session $Session).Content
    $tilePattern = '(?is)<div class="game-tile-wrapper">.*?<a class="game-hover" href="https?://catalogue\.smods\.ru/game/([^"]+)">.*?<h2 class="game-title">(.*?)</h2>.*?<a class="game-buy-btn" href="https?://store\.steampowered\.com/app/(\d+)'
    $matches = [regex]::Matches($html, $tilePattern)

    $rows = @()
    foreach ($m in $matches) {
        $rows += [pscustomobject]@{
            AppId = [int]$m.Groups[3].Value
            Slug  = $m.Groups[1].Value
            Game  = (Html-Decode (($m.Groups[2].Value -replace '<.*?>', '').Trim()))
            Aliases = @()
        }
    }

    return $rows | Sort-Object AppId -Unique
}

function Add-GameAliases {
    param([object[]]$Games)

    $out = @()
    foreach ($g in $Games) {
        $variants = Get-NameVariants -GameName $g.Game -Slug $g.Slug
        $out += [pscustomobject]@{
            AppId = [int]$g.AppId
            Slug = $g.Slug
            Game = $g.Game
            Aliases = $variants
        }
    }
    return $out
}

function Save-GamesCache {
    param(
        [string]$Path,
        [object[]]$Games
    )

    $payload = [pscustomobject]@{
        generated_at = (Get-Date).ToString("s")
        source = $homeUrl
        count = $Games.Count
        games = $Games
    }
    $payload | ConvertTo-Json -Depth 8 | Set-Content -Path $Path -Encoding UTF8
}

function Load-GamesCache {
    param([string]$Path)

    if (-not (Test-Path $Path)) { return $null }
    try {
        $obj = Get-Content -Raw $Path | ConvertFrom-Json
        if (-not $obj.games) { return $null }
        return @($obj.games)
    }
    catch {
        return $null
    }
}

function Resolve-GameSelection {
    param(
        [object[]]$SupportedGames,
        [string]$Game,
        [int]$AppId
    )

    if ($AppId -gt 0) {
        $byId = $SupportedGames | Where-Object { $_.AppId -eq $AppId } | Select-Object -First 1
        if ($byId) { return $byId }
        return [pscustomobject]@{ AppId = $AppId; Slug = $null; Game = "(Unknown in homepage list)" }
    }

    if ([string]::IsNullOrWhiteSpace($Game)) {
        throw "Provide -Game or -AppId."
    }

    if ($Game -match '^\d+$') {
        return Resolve-GameSelection -SupportedGames $SupportedGames -Game $null -AppId ([int]$Game)
    }

    $norm = $Game.Trim().ToLowerInvariant()
    $normKey = Normalize-Name $norm

    $exactSlug = $SupportedGames | Where-Object { $_.Slug.ToLowerInvariant() -eq $norm } | Select-Object -First 1
    if ($exactSlug) { return $exactSlug }

    $exactName = $SupportedGames | Where-Object { $_.Game.ToLowerInvariant() -eq $norm } | Select-Object -First 1
    if ($exactName) { return $exactName }

    $exactAlias = $SupportedGames | Where-Object {
        $_.Aliases -and (($_.Aliases | ForEach-Object { Normalize-Name $_ }) -contains $normKey)
    } | Select-Object -First 1
    if ($exactAlias) { return $exactAlias }

    $contains = $SupportedGames | Where-Object {
        $_.Slug.ToLowerInvariant().Contains($norm) -or $_.Game.ToLowerInvariant().Contains($norm) -or
        ($_.Aliases -and (($_.Aliases | ForEach-Object { Normalize-Name $_ }) -match [regex]::Escape($normKey)))
    } | Select-Object -First 1

    if ($contains) { return $contains }
    throw "Cannot resolve game '$Game'. Run with -ListGames and pick a slug/appid."
}

function Get-Keywords {
    param(
        [string]$Keyword,
        [string]$ListFile
    )

    $items = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($Keyword)) {
        $items.Add($Keyword.Trim())
    }

    if (-not [string]::IsNullOrWhiteSpace($ListFile)) {
        if (-not (Test-Path $ListFile)) {
            throw "List file not found: $ListFile"
        }
        Get-Content $ListFile | ForEach-Object {
            $line = $_.Trim()
            if ($line -and -not $line.StartsWith("#")) {
                $items.Add($line)
            }
        }
    }

    return $items.ToArray()
}

function Find-FirstResultForKeyword {
    param(
        [int]$AppId,
        [string]$SearchText,
        [Microsoft.PowerShell.Commands.WebRequestSession]$Session
    )

    $headers = New-CommonHeaders
    $searchUrl = "$catalogBase/?s=$([uri]::EscapeDataString($SearchText))&app=$AppId"
    $html = (Get-Web -Uri $searchUrl -Headers $headers -Session $Session).Content

    $entryPattern = '(?is)<h2 class="post-title entry-title">\s*<a href="https?://catalogue\.smods\.ru/archives/(\d+)"[^>]*>(.*?)</a>.*?<a class="skymods-excerpt-btn[^"]*" href="(https?://modsbase\.com/[^"]+)"'
    $m = [regex]::Match($html, $entryPattern)
    if (-not $m.Success) { return $null }

    return [pscustomobject]@{
        ArchiveId = $m.Groups[1].Value
        Title     = Html-Decode (($m.Groups[2].Value -replace '<.*?>', '').Trim())
        ModsLink  = $m.Groups[3].Value
        SearchUrl = $searchUrl
    }
}

function Normalize-DirectUrl {
    param([string]$Url)
    if ([string]::IsNullOrWhiteSpace($Url)) { return $null }
    if ($Url.StartsWith("//")) { $Url = "https:$Url" }
    if ($Url -match 'https?://modsbase\.com/.+\.zip\.html') { return $null }
    return $Url
}

function Parse-DirectUrlFromHtml {
    param([string]$Html)

    $candidate = Find-FirstMatch -Text $Html -Patterns @(
        'href="((?:https?:)?//[^"\s]*?/cgi-bin/dl?\.cgi/[^"\s]+)"',
        "href='((?:https?:)?//[^'\s]*?/cgi-bin/dl?\.cgi/[^'\s]+)'",
        'href="((?:https?:)?//[^"\s]+\.zip(?!\.html)(?:\?[^"\s]*)?)"',
        "href='((?:https?:)?//[^'\s]+\.zip(?!\.html)(?:\?[^'\s]*)?)'",
        '(?:location\.href|window\.open)\s*\(\s*["'']((?:https?:)?//[^"''\s]+)["'']\s*\)'
    )
    return Normalize-DirectUrl -Url $candidate
}

function Parse-HiddenInputs {
    param([string]$Html)
    $body = @{}
    $inputTags = [regex]::Matches($Html, '(?is)<input[^>]+type=["'']hidden["''][^>]*>')
    foreach ($tagMatch in $inputTags) {
        $tag = $tagMatch.Value
        $name = Find-FirstMatch -Text $tag -Patterns @('name="([^"]+)"', "name='([^']+)'")
        if ([string]::IsNullOrWhiteSpace($name)) { continue }
        $value = Find-FirstMatch -Text $tag -Patterns @('value="([^"]*)"', "value='([^']*)'")
        if ($null -eq $value) { $value = "" }
        $body[$name] = $value
    }
    return $body
}

function Resolve-DirectDownloadUrl {
    param(
        [string]$ModsLink,
        [string]$RefererUrl,
        [Microsoft.PowerShell.Commands.WebRequestSession]$Session
    )

    $headers = New-CommonHeaders
    $headers["Referer"] = $RefererUrl

    $first = Get-Web -Uri $ModsLink -Headers $headers -Session $Session
    $firstHtml = $first.Content

    $direct = Parse-DirectUrlFromHtml -Html $firstHtml
    if ($direct) { return $direct }

    $action = Find-FirstMatch -Text $firstHtml -Patterns @(
        '<form[^>]+method=["'']post["''][^>]+action=["'']([^"'']+)["'']',
        '<form[^>]+action=["'']([^"'']+)["''][^>]+method=["'']post["'']'
    )
    if ([string]::IsNullOrWhiteSpace($action)) { $action = $ModsLink }
    if ($action.StartsWith("/")) {
        $action = "https://modsbase.com$action"
    }
    elseif ($action.StartsWith("//")) {
        $action = "https:$action"
    }

    $body = Parse-HiddenInputs -Html $firstHtml
    if (-not $body.ContainsKey("method_free")) { $body["method_free"] = "" }

    Start-Sleep -Seconds 3
    $second = Post-Web -Uri $action -Headers $headers -Body $body -Session $Session
    $secondHtml = $second.Content

    return Parse-DirectUrlFromHtml -Html $secondHtml
}

function Get-OutputName {
    param(
        [string]$DirectUrl,
        [string]$FallbackBaseName
    )

    $fileName = $null
    try {
        $uri = [Uri]$DirectUrl
        $fileName = [System.IO.Path]::GetFileName($uri.AbsolutePath)
    }
    catch {
        $fileName = $null
    }

    if ([string]::IsNullOrWhiteSpace($fileName) -or $fileName -match '^dl\.cgi$|^d\.cgi$') {
        $safeBase = ($FallbackBaseName -replace '[\\/:*?"<>|]', '_')
        $fileName = "$safeBase.zip"
    }
    return Html-Decode $fileName
}

$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$config = Load-Config -Path $configPath

if ($config) {
    if (-not $AppId -and $config.default_appid) { $AppId = [int]$config.default_appid }
    if ([string]::IsNullOrWhiteSpace($Game) -and $config.default_game) { $Game = [string]$config.default_game }
    if ([string]::IsNullOrWhiteSpace($OutDir) -and $config.default_outdir) { $OutDir = [string]$config.default_outdir }
    if (-not $RefreshGamesCache -and $config.refresh_games_cache) { $RefreshGamesCache = [bool]$config.refresh_games_cache }
}

$games = Load-GamesCache -Path $gamesCachePath
if ($RefreshGamesCache -or -not $games) {
    Write-Step "Fetching supported games from website..."
    $games = Get-SupportedGames -Session $session
    $games = Add-GameAliases -Games $games
    Save-GamesCache -Path $gamesCachePath -Games $games
    Write-Host "[OK] Games cache saved: $gamesCachePath (count=$($games.Count))" -ForegroundColor Green
}

if ($ListGames) {
    $games |
        Sort-Object Game |
        Select-Object AppId, @{Name="Slug";Expression={ Decode-Slug $_.Slug }}, Game |
        Format-Table -AutoSize
    return
}

$selected = Resolve-GameSelection -SupportedGames $games -Game $Game -AppId $AppId
$keywords = Get-Keywords -Keyword $Keyword -ListFile $ListFile

if ($keywords.Count -eq 0) {
    throw "No keywords provided. Use -Keyword or -ListFile."
}

if ($Limit -gt 0) {
    $keywords = $keywords | Select-Object -First $Limit
}

Write-Host "[GAME] $($selected.Game) | AppId=$($selected.AppId) | Slug=$($selected.Slug)" -ForegroundColor Green
Write-Host "[INFO] Tasks: $($keywords.Count)" -ForegroundColor Green

if (-not $OnlyGetLink -and -not (Test-Path $OutDir)) {
    New-Item -Path $OutDir -ItemType Directory | Out-Null
}

$index = 0
foreach ($item in $keywords) {
    $index++
    Write-Step "[$index/$($keywords.Count)] Search: $item"

    $result = Find-FirstResultForKeyword -AppId $selected.AppId -SearchText $item -Session $session
    if (-not $result) {
        Write-WarnLine "No result found for '$item'"
        continue
    }

    Write-Host "[HIT] $($result.Title)" -ForegroundColor DarkCyan
    Write-Host "[MODS] $($result.ModsLink)" -ForegroundColor DarkCyan

    $direct = Resolve-DirectDownloadUrl -ModsLink $result.ModsLink -RefererUrl $result.SearchUrl -Session $session
    if (-not $direct) {
        Write-WarnLine "Could not resolve direct URL for '$item'"
        continue
    }

    Write-Host "[URL] $direct" -ForegroundColor Green

    if ($OnlyGetLink) { continue }

    $name = Get-OutputName -DirectUrl $direct -FallbackBaseName $result.Title
    $targetPath = Join-Path $OutDir $name
    Write-Step "Download -> $targetPath"
    Invoke-WebRequest -Uri $direct -Headers (New-CommonHeaders) -WebSession $session -OutFile $targetPath -UseBasicParsing
    Write-Host "[DONE] $targetPath" -ForegroundColor Green
}
