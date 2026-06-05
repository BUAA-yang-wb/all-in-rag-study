<script setup lang="ts">
import { computed } from "vue";
import { SlidersHorizontal } from "lucide-vue-next";

import { optionalNumber } from "@/api/payload";
import type { AskFormState, SearchFormState } from "@/types/api";

const props = defineProps<{
  mode: "ask" | "search";
  settings: AskFormState | SearchFormState;
}>();

const askSettings = computed(() => props.settings as AskFormState);
</script>

<template>
  <details class="advanced-box">
    <summary>
      <span>
        <SlidersHorizontal :size="17" aria-hidden="true" />
        高级检索参数
      </span>
      <small>strategy / rerank / context</small>
    </summary>

    <div class="field-grid">
      <label class="field">
        <span>index_backend</span>
        <select v-model="settings.index_backend">
          <option value="milvus">milvus</option>
          <option value="faiss">faiss</option>
        </select>
      </label>

      <label v-if="settings.index_backend === 'milvus'" class="field field--wide">
        <span>milvus_uri</span>
        <input v-model="settings.milvus_uri" type="text" />
      </label>

      <label v-if="settings.index_backend === 'milvus'" class="field field--wide">
        <span>milvus_collection</span>
        <input v-model="settings.milvus_collection" type="text" />
      </label>

      <label class="field">
        <span>检索策略</span>
        <select v-model="settings.strategy">
          <option value="hybrid">hybrid</option>
          <option value="dense">dense</option>
          <option value="bm25">bm25</option>
        </select>
      </label>

      <label class="field">
        <span>candidate_k</span>
        <input
          :value="settings.candidate_k ?? ''"
          type="number"
          min="1"
          max="100"
          placeholder="自动"
          @input="settings.candidate_k = optionalNumber($event)"
        />
      </label>

      <label class="field">
        <span>rrf_k</span>
        <input v-model.number="settings.rrf_k" type="number" min="1" max="200" />
      </label>

      <label class="field">
        <span>rerank_top_n</span>
        <input v-model.number="settings.rerank_top_n" type="number" min="1" max="100" />
      </label>

      <label class="field field--wide">
        <span>rerank_model</span>
        <input v-model="settings.rerank_model" type="text" />
      </label>

      <label class="field">
        <span>rerank_device</span>
        <input v-model="settings.rerank_device" type="text" />
      </label>

      <label class="field">
        <span>rerank_batch_size</span>
        <input v-model.number="settings.rerank_batch_size" type="number" min="1" max="32" />
      </label>

      <label class="field">
        <span>min_chunk_chars</span>
        <input v-model.number="settings.min_chunk_chars" type="number" min="0" />
      </label>

      <label class="field">
        <span>preview_chars</span>
        <input v-model.number="settings.preview_chars" type="number" min="50" max="1000" />
      </label>

      <label class="field">
        <span>course</span>
        <input v-model="settings.course" type="text" placeholder="计网 / 编译原理" />
      </label>

      <label class="field">
        <span>category</span>
        <input v-model="settings.category" type="text" placeholder="课件 / 往届期末试题" />
      </label>

      <label class="field field--wide">
        <span>source_name</span>
        <input v-model="settings.source_name" type="text" />
      </label>

      <label class="field">
        <span>page</span>
        <input v-model="settings.page" type="text" />
      </label>

      <label class="field">
        <span>modality</span>
        <input v-model="settings.modality" type="text" placeholder="text" />
      </label>

      <label class="field">
        <span>evidence_kind</span>
        <input v-model="settings.evidence_kind" type="text" placeholder="native_text" />
      </label>

      <template v-if="mode === 'ask'">
        <label class="field">
          <span>temperature</span>
          <input
            v-model.number="askSettings.temperature"
            type="number"
            min="0"
            max="2"
            step="0.1"
          />
        </label>

        <label class="field">
          <span>max_tokens</span>
          <input v-model.number="askSettings.max_tokens" type="number" min="128" max="4096" />
        </label>

        <label class="field">
          <span>max_context_chars</span>
          <input v-model.number="askSettings.max_context_chars" type="number" min="500" />
        </label>

        <label class="field">
          <span>单来源上下文</span>
          <input
            v-model.number="askSettings.max_context_chars_per_source"
            type="number"
            min="200"
          />
        </label>
      </template>
    </div>

    <div class="toggle-row advanced-toggle-row">
      <label class="switch">
        <input v-model="settings.use_metadata_routing" type="checkbox" />
        <span>Metadata routing</span>
      </label>
    </div>
  </details>
</template>
