<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";

import {
  askQuestion,
  fetchHealth,
  loadIndex as loadIndexRequest,
  searchEvidence,
} from "@/api/client";
import AppHeader from "@/components/AppHeader.vue";
import AskForm from "@/components/AskForm.vue";
import AnswerPanel from "@/components/AnswerPanel.vue";
import NoticeBar from "@/components/NoticeBar.vue";
import SearchWorkbench from "@/components/SearchWorkbench.vue";
import StatusStrip from "@/components/StatusStrip.vue";
import type {
  AskRequest,
  AskResponse,
  HealthResponse,
  NoticeType,
  SearchRequest,
  SearchResponse,
} from "@/types/api";

const health = ref<HealthResponse | null>(null);
const askResult = ref<AskResponse | null>(null);
const searchResult = ref<SearchResponse | null>(null);
const notice = reactive<{ text: string; type: NoticeType }>({
  text: "",
  type: "info",
});
const loading = reactive({
  health: false,
  index: false,
  ask: false,
  search: false,
});

function showNotice(text: string, type: NoticeType = "error") {
  notice.text = text;
  notice.type = type;
}

function clearNotice() {
  notice.text = "";
}

async function refreshHealth(silent = false) {
  loading.health = true;
  try {
    health.value = await fetchHealth();
    if (!silent) {
      showNotice("服务状态已刷新。", "success");
    }
  } catch (error) {
    showNotice(error instanceof Error ? error.message : String(error), "error");
  } finally {
    loading.health = false;
  }
}

async function loadIndex() {
  loading.index = true;
  clearNotice();
  try {
    const response = await loadIndexRequest();
    await refreshHealth(true);
    showNotice(response.message || "索引已加载。", "success");
  } catch (error) {
    showNotice(error instanceof Error ? error.message : String(error), "error");
  } finally {
    loading.index = false;
  }
}

async function submitAsk(payload: AskRequest) {
  loading.ask = true;
  clearNotice();
  try {
    askResult.value = await askQuestion(payload);
    await refreshHealth(true);
  } catch (error) {
    showNotice(error instanceof Error ? error.message : String(error), "error");
  } finally {
    loading.ask = false;
  }
}

async function submitSearch(payload: SearchRequest) {
  loading.search = true;
  clearNotice();
  try {
    searchResult.value = await searchEvidence(payload);
    await refreshHealth(true);
  } catch (error) {
    showNotice(error instanceof Error ? error.message : String(error), "error");
  } finally {
    loading.search = false;
  }
}

onMounted(() => {
  void refreshHealth(true);
});
</script>

<template>
  <main class="app-shell">
    <AppHeader
      :health="health"
      :loading-health="loading.health"
      :loading-index="loading.index"
      @refresh="refreshHealth()"
      @load-index="loadIndex"
    />

    <StatusStrip :health="health" />
    <NoticeBar :text="notice.text" :type="notice.type" />

    <section class="workspace-grid" aria-label="课程问答">
      <AskForm :busy="loading.ask" @submit="submitAsk" />
      <AnswerPanel :result="askResult" :busy="loading.ask" />
    </section>

    <SearchWorkbench
      :result="searchResult"
      :busy="loading.search"
      @submit="submitSearch"
    />
  </main>
</template>
