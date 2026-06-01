<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { Search, SendHorizontal } from "lucide-vue-next";

import { buildSearchRequest, optionalNumber } from "@/api/payload";
import AdvancedSettings from "@/components/AdvancedSettings.vue";
import EvidenceList from "@/components/EvidenceList.vue";
import type { SearchFormState, SearchRequest, SearchResponse } from "@/types/api";

const props = defineProps<{
  result: SearchResponse | null;
  busy: boolean;
}>();

const emit = defineEmits<{
  submit: [payload: SearchRequest];
}>();

const localError = ref("");
const form = reactive<SearchFormState>({
  query: "",
  top_k: 5,
  candidate_k: null,
  strategy: "hybrid",
  rrf_k: 60,
  use_rerank: true,
  rerank_top_n: 20,
  rerank_model: "BAAI/bge-reranker-base",
  rerank_batch_size: 8,
  rerank_device: "auto",
  rerank_local_files_only: true,
  use_parent_context: true,
  min_chunk_chars: 20,
  preview_chars: 220,
});

const resultMeta = computed(() => {
  if (!props.result) return "尚未请求";
  return `${props.result.strategy} / top_k=${props.result.top_k} / ${
    props.result.retrieval.length || props.result.citations.length
  } 条`;
});

function submitForm() {
  localError.value = "";
  if (!form.query.trim()) {
    localError.value = "请输入检索查询。";
    return;
  }
  emit("submit", buildSearchRequest(form));
}
</script>

<template>
  <section class="debug-section" aria-label="检索调试">
    <form class="paper-panel search-form" @submit.prevent="submitForm">
      <div class="section-title">
        <span class="section-icon"><Search :size="19" /></span>
        <div>
          <h2>检索调试</h2>
          <p>调用 POST /search，不触发 LLM。</p>
        </div>
      </div>

      <label class="field field--textarea">
        <span>查询</span>
        <textarea
          v-model="form.query"
          placeholder="例如：运输层的主要功能是什么？"
        />
      </label>

      <div class="field-grid field-grid--compact">
        <label class="field">
          <span>top_k</span>
          <input v-model.number="form.top_k" type="number" min="1" max="20" />
        </label>
        <label class="field">
          <span>candidate_k</span>
          <input
            :value="form.candidate_k ?? ''"
            type="number"
            min="1"
            max="100"
            placeholder="自动"
            @input="form.candidate_k = optionalNumber($event)"
          />
        </label>
      </div>

      <div class="toggle-row">
        <label class="switch">
          <input v-model="form.use_rerank" type="checkbox" />
          <span>Rerank 精排</span>
        </label>
        <label class="switch">
          <input v-model="form.use_parent_context" type="checkbox" />
          <span>父文档上下文</span>
        </label>
        <label class="switch">
          <input v-model="form.rerank_local_files_only" type="checkbox" />
          <span>仅本地模型</span>
        </label>
      </div>

      <AdvancedSettings mode="search" :settings="form" />

      <p v-if="localError" class="inline-error">{{ localError }}</p>

      <div class="panel-actions">
        <button class="button button--primary" type="submit" :disabled="busy">
          <SendHorizontal :size="17" />
          {{ busy ? "检索中" : "开始检索" }}
        </button>
        <span class="action-hint">适合比较 dense / BM25 / hybrid 召回效果。</span>
      </div>
    </form>

    <section class="paper-panel search-results">
      <div class="section-title">
        <span class="section-icon"><Search :size="19" /></span>
        <div>
          <h2>检索证据</h2>
          <p>{{ resultMeta }}</p>
        </div>
      </div>

      <div v-if="result?.rerank_error" class="notice notice--warning">
        Rerank 回退：{{ result.rerank_error }}
      </div>

      <EvidenceList
        :items="result?.retrieval?.length ? result.retrieval : result?.citations || []"
        empty-text="检索结果会显示来源、页码、章节、分数和命中片段。"
      />
    </section>
  </section>
</template>
