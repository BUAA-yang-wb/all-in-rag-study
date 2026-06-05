param(
    [string]$MilvusUri = "http://localhost:19530",
    [string]$Collection = "course_rag_v2_text",
    [string]$Query = "FIRST FOLLOW 表格",
    [int]$TopK = 3
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $RepoRoot "rag\Scripts\python.exe"
$Indexer = Join-Path $RepoRoot "course_rag\app\rag\milvus_index.py"

if (-not (Test-Path $Python)) {
    throw "Project Python not found: $Python"
}

& $Python -X utf8 $Indexer --check --uri $MilvusUri --collection $Collection --query $Query --top-k $TopK
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
