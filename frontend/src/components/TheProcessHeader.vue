<template>
  <header class="flex h-[clamp(2.5rem,7vh,4rem)] items-center gap-6 border-b border-[#ebd8cc] bg-[#fffaf7] px-6 lg:px-8">
    <div class="flex shrink-0 gap-2" aria-label="Indicadores da janela">
      <span class="size-3 rounded-full bg-[#ff625c]"></span>
      <span class="size-3 rounded-full bg-[#ffbd2e]"></span>
      <span class="size-3 rounded-full bg-[#27c840]"></span>
    </div>

    <ol class="hidden min-w-0 flex-1 items-center justify-center gap-3 text-sm xl:flex" aria-label="Etapas do processo">
      <li class="flex shrink-0 items-center gap-2.5 font-medium text-[#c2560b]">
        <span class="grid size-[34px] place-items-center rounded-full border-[1.5px] border-[#c2560b]" aria-hidden="true">
          <svg class="size-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><rect x="7.25" y="2.75" width="5.5" height="9.5" rx="2.75" /><path d="M4.75 9.5a5.25 5.25 0 0 0 10.5 0M10 14.75v2.5" /></svg>
        </span>
        Voz/Texto
      </li>
      <li class="h-px min-w-6 flex-1 bg-[#e5d3c8]" aria-hidden="true"></li>
      <li class="flex shrink-0 items-center gap-2.5 text-[#a79489]">
        <span class="grid size-[34px] place-items-center rounded-full border border-[#e5d3c8]" aria-hidden="true">
          <svg class="size-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M3.25 6.25a2.5 2.5 0 0 1 2.5-2.5h8.5a2.5 2.5 0 0 1 2.5 2.5v5a2.5 2.5 0 0 1-2.5 2.5H8l-4.75 3.25z" /></svg>
        </span>
        Conversa
      </li>
      <li class="h-px min-w-6 flex-1 bg-[#e5d3c8]" aria-hidden="true"></li>
      <li class="flex shrink-0 items-center gap-2.5 text-[#a79489]">
        <span class="grid size-[34px] place-items-center rounded-full border border-[#e5d3c8]" aria-hidden="true">
          <svg class="size-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><circle cx="10" cy="10" r="7.25" /><path d="M8.25 7.1 13 10l-4.75 2.9z" /></svg>
        </span>
        Simulação
      </li>
      <li class="h-px min-w-6 flex-1 bg-[#e5d3c8]" aria-hidden="true"></li>
      <li class="flex shrink-0 items-center gap-2.5 text-[#a79489]">
        <span class="grid size-[34px] place-items-center rounded-full border border-[#e5d3c8]" aria-hidden="true">
          <svg class="size-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M3.75 5.25a1.5 1.5 0 0 1 1.5-1.5h7.5l3 3v8a1.5 1.5 0 0 1-1.5 1.5h-9a1.5 1.5 0 0 1-1.5-1.5z" /><path d="M6.75 3.75v4h6.5M6.75 16.25v-4h6.5v4" /></svg>
        </span>
        Salvar
      </li>
    </ol>

    <details class="relative ml-auto shrink-0">
      <summary class="flex cursor-pointer list-none items-center gap-2 rounded-full border border-[#ead4c7] bg-white/80 py-1 pr-2 pl-1.5 text-sm text-[#5e473b] transition hover:bg-white [&::-webkit-details-marker]:hidden">
        <span class="grid size-7 place-items-center rounded-full bg-[#6d4030] text-xs font-semibold text-white" aria-hidden="true">U</span>
        <span class="hidden lg:block">Perfil</span>
        <svg class="size-3 text-[#9c8174]" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true"><path d="M2 4.25h8L6 9z" /></svg>
      </summary>
      <div class="absolute top-[calc(100%+.5rem)] right-0 z-10 w-52 rounded-lg border border-[#ead4c7] bg-white p-3 shadow-[0_12px_30px_-12px_rgba(60,30,15,0.35)]">
        <p class="text-sm font-semibold text-[#2e1a10]">Perfil do usuário</p>
        <p class="mt-1 text-xs leading-5 text-[#80695c]">A saída da conta será conectada ao login.</p>
        <button type="button" disabled class="mt-3 flex w-full items-center justify-center gap-2 rounded-md border border-[#e4cfc3] px-3 py-2 text-sm font-medium text-[#9c8174] disabled:cursor-not-allowed disabled:opacity-70">
          Sair da conta
        </button>
      </div>
    </details>
  </header>
</template>
