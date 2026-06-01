<script setup lang="ts">
import { computed, ref } from "vue";
import { Bot, Braces, Files, LibraryBig, NotebookTabs } from "lucide-vue-next";

import EvidenceList from "@/components/EvidenceList.vue";
import type { AskResponse } from "@/types/api";

const props = defineProps<{
  result: AskResponse | null;
  busy: boolean;
}>();

const activeTab = ref<"citations" | "retrieval" | "raw">("citations");

const answerText = computed(() => {
  if (props.busy) return "正在整理课程资料、检索引用并生成回答...";
  return props.result?.answer || "问题提交后，答案会显示在这里。";
});

const answerMeta = computed(() => {
  if (!props.result) return "尚未请求";
  const refs = props.result.citations.length;
  const pipeline = props.result.pipeline.join(" -> ");
  return `${refs} 条引用 / ${pipeline}`;
});
</script>

<template>
  <section class="paper-panel answer-panel">
    <div class="answer-head">
      <div class="section-title">
        <span class="section-icon"><Bot :size="19" /></span>
        <div>
          <h2>回答阅读</h2>
          <p>{{ answerMeta }}</p>
        </div>
      </div>
      <span
        class="status-pill"
        :class="result?.used_llm ? 'status-pill--ok' : 'status-pill--warn'"
      >
        {{ result ? (result.used_llm ? "LLM 已使用" : "检索回退") : "LLM -" }}
      </span>
    </div>

    <div v-if="result?.llm_error" class="notice notice--warning">
      LLM 调用失败：{{ result.llm_error }}
    </div>
    <div v-if="result?.rerank_error" class="notice notice--warning">
      Rerank 回退：{{ result.rerank_error }}
    </div>

    <article class="answer-sheet" :class="{ 'answer-sheet--busy': busy }">
      {{ answerText }}
    </article>

    <div class="tabs" aria-label="问答结果视图">
      <button
        class="tab-button"
        :class="{ active: activeTab === 'citations' }"
        type="button"
        @click="activeTab = 'citations'"
      >
        <LibraryBig :size="16" />
        引用
      </button>
      <button
        class="tab-button"
        :class="{ active: activeTab === 'retrieval' }"
        type="button"
        @click="activeTab = 'retrieval'"
      >
        <Files :size="16" />
        检索
      </button>
      <button
        class="tab-button"
        :class="{ active: activeTab === 'raw' }"
        type="button"
        @click="activeTab = 'raw'"
      >
        <Braces :size="16" />
        JSON
      </button>
    </div>

    <EvidenceList
      v-if="activeTab === 'citations'"
      :items="result?.citations || []"
      empty-text="提交问题后会显示引用。"
    />
    <EvidenceList
      v-else-if="activeTab === 'retrieval'"
      :items="result?.retrieval || []"
      empty-text="提交问题后会显示检索片段。"
    />
    <pre v-else class="json-block">{{ JSON.stringify(result || {}, null, 2) }}</pre>

    <div class="notebook-foot">
      <NotebookTabs :size="16" aria-hidden="true" />
      <span>{{ result?.question || "等待一个课程问题" }}</span>
    </div>
  </section>
</template>
