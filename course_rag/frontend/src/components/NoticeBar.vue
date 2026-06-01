<script setup lang="ts">
import { AlertCircle, CheckCircle2, Info, TriangleAlert } from "lucide-vue-next";

import type { NoticeType } from "@/types/api";

defineProps<{
  text: string;
  type: NoticeType;
}>();
</script>

<template>
  <div v-if="text" class="notice" :class="`notice--${type}`" role="status">
    <CheckCircle2 v-if="type === 'success'" :size="18" aria-hidden="true" />
    <TriangleAlert v-else-if="type === 'warning'" :size="18" aria-hidden="true" />
    <AlertCircle v-else-if="type === 'error'" :size="18" aria-hidden="true" />
    <Info v-else :size="18" aria-hidden="true" />
    <span>{{ text }}</span>
  </div>
</template>
