<template>
  <div class="flex flex-col items-center">
    <button
      type="button"
      disabled
      aria-label="Iniciar gravação"
      class="grid size-28 cursor-not-allowed place-items-center rounded-full bg-[#f97518] text-white shadow-[0_16px_40px_-16px_rgba(249,117,24,0.45)] sm:size-36"
    >
      <svg
        class="size-12"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        aria-hidden="true"
      >
        <rect x="9" y="2" width="6" height="13" rx="3" />
        <path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3" />
      </svg>
    </button>
    <p class="mt-6 text-sm text-[#8c7b72] sm:text-base">Clique para iniciar a gravação</p>
  </div>
</template>
