<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>();
</script>

<template>
  <main id="main-content" class="auth-layout min-h-dvh">
    <div class="mx-auto grid min-h-dvh max-w-7xl items-center gap-14 px-6 py-10 lg:grid-cols-2 lg:gap-24 lg:px-12">
      <div class="max-w-lg">
        <RouterLink to="/" class="inline-flex items-center gap-3 text-xl font-bold tracking-tight" aria-label="Ferelix">
          <span class="flex size-10 items-center justify-center rounded-xl bg-primary-500 text-white" aria-hidden="true">F</span>
          <span translate="no">Ferelix<span class="text-primary-400">.</span></span>
        </RouterLink>
        <p class="mt-16 hidden text-xs font-semibold uppercase tracking-[0.25em] text-primary-300 lg:block">{{ $t('auth.yourLibrary') }}</p>
        <h2 class="mt-5 hidden text-5xl font-semibold leading-[1.12] tracking-tight text-balance lg:block">{{ $t('auth.tagline') }}</h2>
        <p class="mt-6 hidden max-w-md text-base leading-7 text-muted lg:block">{{ $t('auth.description') }}</p>
      </div>
      <section class="surface-panel w-full max-w-md justify-self-center p-7 sm:p-10" :aria-label="title">
        <h1 class="text-3xl font-semibold tracking-tight">{{ title }}</h1>
        <p v-if="subtitle" class="mt-3 text-sm leading-6 text-muted">{{ subtitle }}</p>
        <div class="mt-8"><slot /></div>
      </section>
    </div>
  </main>
</template>
