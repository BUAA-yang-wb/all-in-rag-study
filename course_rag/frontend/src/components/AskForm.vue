<script setup lang="ts">
import { reactive, ref } from "vue";
import { MessageSquareText, SendHorizontal } from "lucide-vue-next";

import { buildAskRequest, optionalNumber } from "@/api/payload";
import AdvancedSettings from "@/components/AdvancedSettings.vue";
import type { AskFormState, AskRequest } from "@/types/api";

defineProps<{
  busy: boolean;
}>();

const emit = defineEmits<{
  submit: [payload: AskRequest];
}>();

const localError = ref("");
const form = reactive<AskFormState>({
  question: "",
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
  use_llm: true,
  use_parent_context: true,
  min_chunk_chars: 20,
  max_context_chars: 6000,
  max_context_chars_per_source: 1600,
  preview_chars: 220,
  temperature: 0.1,
  max_tokens: 1500,
  use_metadata_routing: true,
  course: "",
  category: "",
  source_name: "",
  page: "",
  modality: "",
  evidence_kind: "",
});

function submitForm() {
  localError.value = "";
  if (!form.question.trim()) {
    localError.value = "请输入一个课程问题。";
    return;
  }
  emit("submit", buildAskRequest(form));
}
</script>

<template>
  <form class="paper-panel question-panel" @submit.prevent="submitForm">
    <div class="section-title">
      <span class="section-icon"><MessageSquareText :size="19" /></span>
      <div>
        <h2>提问笔记</h2>
        <p>调用 POST /ask，可选择是否启用 LLM 生成。</p>
      </div>
    </div>

    <label class="field field--textarea">
      <span>问题</span>
      <textarea
        v-model="form.question"
        placeholder="例如：编译过程有哪些阶段？请结合课程资料给出引用。"
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
        <input v-model="form.use_llm" type="checkbox" />
        <span>使用 LLM</span>
      </label>
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

    <AdvancedSettings mode="ask" :settings="form" />

    <p v-if="localError" class="inline-error">{{ localError }}</p>

    <div class="panel-actions">
      <button class="button button--primary" type="submit" :disabled="busy">
        <SendHorizontal :size="17" />
        {{ busy ? "请求中" : "发送问题" }}
      </button>
      <span class="action-hint">建议先用 use_llm=false 做离线验证。</span>
    </div>
  </form>
</template>
