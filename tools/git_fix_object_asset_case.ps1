# GitHub(대소문자 구분)용 object PNG 파일명 수정 — git mv 2단계
# 저장소 루트에서: powershell -ExecutionPolicy Bypass -File tools\git_fix_object_asset_case.ps1
#
# 사전 조건: 이 폴더가 git clone 된 저장소여야 합니다 (.git 존재).

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Obj = Join-Path $Root "assets\images\object"

if (-not (Test-Path (Join-Path $Root ".git"))) {
    Write-Error "이 폴더에 .git 이 없습니다. GitHub에서 clone 한 뒤 이 스크립트를 실행하세요."
}

Set-Location $Obj
$git = Get-Command git -ErrorAction Stop

$renames = @(
    @("Tree1.png","tree1.png"), @("Tree2.png","tree2.png"), @("Tree3.png","tree3.png"),
    @("Tree4.png","tree4.png"), @("Tree5.png","tree5.png"), @("Tree6.png","tree6.png"), @("Tree7.png","tree7.png"),
    @("Bush1.png","bush1.png"), @("Bush2.png","bush2.png"),
    @("Plant1.png","plant1.png"), @("Plant2.png","plant2.png"), @("Plant3.png","plant3.png"),
    @("Plant4.png","plant4.png"), @("Plant5.png","plant5.png"),
    @("tv.png","TV.png")
)

function Git-Mv-Case($src, $dst) {
    $trackedSrc = $false
    & $git ls-files --error-unmatch $src 2>$null
    if ($LASTEXITCODE -eq 0) { $trackedSrc = $true }

    if ($trackedSrc) {
        if ($src -ceq $dst) { return }
        $tmp = "__case_tmp_${src}"
        & $git mv $src $tmp
        & $git mv $tmp $dst
        Write-Host "git mv: $src -> $dst"
        return
    }

    & $git ls-files --error-unmatch $dst 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "already tracked: $dst"
        return
    }

    if (Test-Path $src) {
        if ($src -cne $dst) {
            $mid = "__case_tmp_$([guid]::NewGuid().ToString()).png"
            Rename-Item -LiteralPath $src -NewName (Split-Path $mid -Leaf)
            Rename-Item -LiteralPath $mid -NewName $dst
        }
        & $git add $dst
        Write-Host "add: $dst"
        return
    }

    if (Test-Path $dst) {
        Write-Host "skip, exists: $dst"
        return
    }

    Write-Host "missing: $src / $dst"
}

foreach ($pair in $renames) {
    Git-Mv-Case $pair[0] $pair[1]
}

Write-Host "Done. git status -> commit -> push"
