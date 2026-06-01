<script setup lang="ts">
import { BookOpenText, DatabaseZap, RefreshCcw, ScrollText } from "lucide-vue-next";

import type { HealthResponse } from "@/types/api";

defineProps<{
  health: HealthResponse | null;
  loadingHealth: boolean;
  loadingIndex: boolean;
}>();

defineEmits<{
  refresh: [];
  loadIndex: [];
}>();
</script>

<template>
  <header class="app-header">
    <div class="brand-block">
      <div class="brand-mark" aria-hidden="true">
        <BookOpenText :size="28" />
      </div>
      <div>
        <p class="eyebrow">Course RAG Notebook</p>
        <h1>课程资料问答工作台</h1>
        <p class="header-copy">
          把本地课程文档当作可追溯的学习笔记来提问，答案、引用和检索链路放在同一张桌面上。
        </p>
      </div>
    </div>

    <div class="header-actions">
      <span
        class="status-pill"
        :class="health?.status === 'ok' ? 'status-pill--ok' : 'status-pill--warn'"
      >
        {{ health?.status || "checking" }}
      </span>
      <button class="button button--soft" type="button" @click="$emit('refresh')">
        <RefreshCcw :size="17" :class="{ 'icon-spin': loadingHealth }" />
        刷新状态
      </button>
      <button
        class="button button--ink"
        type="button"
        :disabled="loadingIndex"
        @click="$emit('loadIndex')"
      >
        <DatabaseZap :size="17" />
        {{ loadingIndex ? "加载中" : "加载索引" }}
      </button>
      <a class="button button--ghost-link" href="/docs" target="_blank" rel="noreferrer">
        <ScrollText :size="17" />
        Swagger
      </a>
    </div>
  </header>
</template>
