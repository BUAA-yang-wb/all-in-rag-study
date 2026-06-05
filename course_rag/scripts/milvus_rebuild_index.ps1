param(
    [string]$MilvusUri = "http://localhost:19530",
    [string]$Collection = "course_rag_v2_text",
    [int]$BatchSize = 256
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Python = Join-Path $RepoRoot "rag\Scripts\python.exe"
$Indexer = Join-Path $RepoRoot "course_rag\app\rag\milvus_index.py"

if (-not (Test-Path $Python)) {
    throw "Project Python not found: $Python"
}

& $Python -X utf8 $Indexer --uri $MilvusUri --collection $Collection --batch-size $BatchSize --drop-existing --rebuild-docstore
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
