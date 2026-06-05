<script setup lang="ts">
import { Activity, Archive, Boxes, Cpu, Server } from "lucide-vue-next";

import type { HealthResponse } from "@/types/api";

defineProps<{
  health: HealthResponse | null;
}>();
</script>

<template>
  <section class="status-grid" aria-label="服务与索引状态">
    <article class="metric-card">
      <Activity :size="19" aria-hidden="true" />
      <span>服务状态</span>
      <strong>{{ health?.status || "-" }}</strong>
    </article>
    <article class="metric-card">
      <Archive :size="19" aria-hidden="true" />
      <span>SQLite Docstore</span>
      <strong>{{ health ? (health.docstore_readable ? `${health.docstore_chunks} chunks` : "不可读") : "-" }}</strong>
    </article>
    <article class="metric-card">
      <Boxes :size="19" aria-hidden="true" />
      <span>Milvus 对齐</span>
      <strong>
        {{
          health?.milvus_aligned_with_docstore === true
            ? "一致"
            : health?.milvus_aligned_with_docstore === false
              ? "不一致"
              : "-"
        }}
      </strong>
    </article>
    <article class="metric-card">
      <Server :size="19" aria-hidden="true" />
      <span>Milvus</span>
      <strong>{{ health ? (health.milvus_connected ? "已连接" : "未连接") : "-" }}</strong>
    </article>
    <article class="metric-card metric-card--wide">
      <Cpu :size="19" aria-hidden="true" />
      <span>Milvus entities / Embedding / Collection</span>
      <strong>
        {{
          health?.index
            ? `${health.milvus_entity_count ?? health.index.vectors} / ${health.index.embedding_model || "-"} / ${health.milvus_collection || "-"}`
            : health?.milvus_collection || "-"
        }}
      </strong>
    </article>
  </section>
</template>
