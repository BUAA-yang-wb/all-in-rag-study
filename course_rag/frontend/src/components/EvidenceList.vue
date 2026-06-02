<script setup lang="ts">
import { FileText, GitBranch, Hash, Layers, MapPinned } from "lucide-vue-next";

import type { Citation } from "@/types/api";

defineProps<{
  items: Citation[];
  emptyText: string;
}>();

function sourceName(item: Citation): string {
  return item.source_name || item.source || "unknown source";
}

function locationText(item: Citation): string {
  const parts: string[] = [];
  if (item.course) parts.push(item.course);
  if (item.category) parts.push(item.category);
  if (item.page !== null && item.page !== undefined && item.page !== "") {
    parts.push(`page ${item.page}`);
  }
  if (item.section_path || item.section) {
    parts.push(item.section_path || item.section || "");
  }
  return parts.filter(Boolean).join(" / ");
}

function previewText(item: Citation): string {
  return item.context_preview || item.text || item.chunk_preview || "无片段预览";
}

function fixedScore(value: unknown): string {
  const score = Number(value);
  return Number.isFinite(score) ? score.toFixed(4) : "-";
}

function diagnosticChips(item: Citation): string[] {
  const chips: string[] = [];
  if (item.modality) chips.push(item.modality);
  if (item.evidence_kind) chips.push(item.evidence_kind);
  if (item.parser_backend) chips.push(item.parser_backend);
  if (item.retrieval_strategy) chips.push(item.retrieval_strategy);
  if (item.retrievers?.length) chips.push(item.retrievers.join("+"));
  if (item.rerank_score !== null && item.rerank_score !== undefined) {
    chips.push(`rerank ${fixedScore(item.rerank_score)}`);
  }
  if (item.rrf_score !== null && item.rrf_score !== undefined) {
    chips.push(`rrf ${fixedScore(item.rrf_score)}`);
  }
  if (item.metadata_boost && item.metadata_boost > 1) {
    chips.push(`metadata x${fixedScore(item.metadata_boost)}`);
  }
  if (item.matched_filters?.length) {
    chips.push(`filter ${item.matched_filters.join("+")}`);
  }
  return chips;
}
</script>

<template>
  <div v-if="!items.length" class="empty-state">
    {{ emptyText }}
  </div>

  <div v-else class="evidence-list">
    <article v-for="item in items" :key="`${item.id}-${item.rank ?? 'r'}`" class="evidence-card">
      <div class="evidence-head">
        <div class="source-line">
          <span class="rank-badge">#{{ item.rank ?? item.id }}</span>
          <strong>{{ sourceName(item) }}</strong>
        </div>
        <span class="score-pill">
          <Hash :size="14" aria-hidden="true" />
          {{ fixedScore(item.score) }}
        </span>
      </div>

      <div class="meta-line">
        <MapPinned :size="15" aria-hidden="true" />
        <span>{{ locationText(item) || "no location metadata" }}</span>
      </div>

      <p class="evidence-text">{{ previewText(item) }}</p>

      <div class="chip-row">
        <span v-if="item.evidence_id" class="mini-chip">
          <Layers :size="13" aria-hidden="true" />
          {{ item.evidence_id }}
        </span>
        <span v-if="item.chunk_id" class="mini-chip">
          <FileText :size="13" aria-hidden="true" />
          {{ item.chunk_id }}
        </span>
        <span v-for="chip in diagnosticChips(item)" :key="chip" class="mini-chip">
          <GitBranch :size="13" aria-hidden="true" />
          {{ chip }}
        </span>
      </div>
    </article>
  </div>
</template>
