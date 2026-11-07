<script setup lang="ts">
import { ref } from "vue";

const model = defineModel<string>({ required: true });
defineProps<{
  id: string;
  label: string;
  autocomplete: "current-password" | "new-password";
  required?: boolean;
  help?: string;
}>();
const visible = ref(false);
</script>

<template>
  <div class="space-y-2">
    <label :for="id" class="field-label">{{ label }}</label>
    <div class="relative">
      <input
        :id="id"
        v-model="model"
        :name="id"
        :type="visible ? 'text' : 'password'"
        :autocomplete="autocomplete"
        :required="required"
        :aria-describedby="help ? `${id}-help` : undefined"
        maxlength="1024"
        class="field-input pr-24"
      />
      <button
        type="button"
        class="absolute inset-y-1 right-1 rounded-lg px-3 text-xs font-semibold text-gray-300 hover:bg-white/10 hover:text-white"
        :aria-pressed="visible"
        :aria-controls="id"
        @click="visible = !visible"
      >
        {{ visible ? $t('auth.hidePassword') : $t('auth.showPassword') }}
      </button>
    </div>
    <p v-if="help" :id="`${id}-help`" class="text-xs leading-relaxed text-muted">{{ help }}</p>
  </div>
</template>
