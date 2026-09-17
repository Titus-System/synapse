<template>
    <div class="p-10">
    <!-- Simulação -->
        <div class="mb-12">
            <div class="mb-11">
                <h1 class="text-3xl text-[#2B160D] mb-2">Simulação</h1>
                <p class="text-[#584237]">Verifique a viabilidade da sua regra de negócio.</p>
            </div>
            <div>
                <div class="flex flex-row">
                    <div class="w-[50%]">
                        <h3 class="font-bold">Regra estruturada</h3>
                        <hr class="mb-4 border border-[#FFDBCD] w-[89%]">
                            <form class="flex flex-row gap-22">
                                <div class="flex flex-col">
                                    <div class="flex flex-col">
                                        <label for="vigencia" class="mb-1 text-[#584237]">Vigência</label>
                                        <input id="vigencia" type="text" class="bg-[#FFE9E1] text-[#2B160D] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]"/>
                                    </div>
                                    <div class="flex flex-col">
                                        <label for="loja" class="mb-1 text-[#584237]">Loja</label>
                                        <input id="loja" type="text" class="bg-[#FFE9E1] text-[#2B160D] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]"/>
                                    </div>

                                    <div class="flex flex-col">
                                        <label for="marca" class="mb-1 text-[#584237]">Marca</label>
                                        <input id="marca" type="text" class="bg-[#FFE9E1] text-[#2B160D] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]" />
                                    </div>
                                </div>
                                <div class="flex flex-col">
                                    <label for="cargo" class="mb-1 text-[#584237]">Cargo</label>
                                    <input id="cargo" type="text" class="bg-[#FFE9E1] text-[#2B160D] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]"/>

                                    <label for="meta" class="mb-1 text-[#584237]">Meta</label>
                                    <input id="meta" type="text" class="bg-[#FFE9E1] text-[#2B160D] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]"/>

                                    <label for="percentual" class="mb-1 text-[#584237]">Percentual</label>
                                    <input id="percentual" type="text" class="bg-[#FFE9E1] text-[#2B160D] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]"/>
                                </div>
                            </form>
                    </div>
                    <div class="border-2 border-[#DFC0B2] rounded-lg w-[50%] p-5">
                        <h3 class="font-bold">Dados da simulação</h3>
                        <hr class="mb-4 border border-[#FFDBCD]">
                        <div class="flex flex-col mb-8">
                            <label for="percentual" class="mb-1 text-[#584237]">Total de comissionamento</label>
                            <input id="percentual" type="text" placeholder="R$ X,00"  class="bg-[#FFE9E1] rounded-lg border-2 border-[#8B7265] text-[#2B160D] px-3.5 py-3 w-full"/>
                        </div>
                        <!-- Aprovada -->
                        <div class="flex flex-col w-[80%] rounded-lg mb-3 border-l-8 border-r border-t border-b border-l-[#14532D] border-r-[#14532D]/20 border-t-[#14532D]/20 border-b-[#14532D]/20 bg-[#F4ECE6]/50 p-3">
                            <div class="flex flex-row items-center gap-3.5">
                                <font-awesome-icon
                                    :icon="['far', 'circle-check']"
                                    class="text-2xl text-[#14532D]"
                                />
                                <div class="flex flex-col">
                                    <h4 class="text-[#14532D] mb-1 font-bold">Resultado: Regra de negócio aprovada!</h4>
                                    <ul class="list-disc list-inside">
                                        <li class="text-[#584237]">A regra de negócio cabe no seu orçamento.</li>
                                    </ul>
                                </div>
                            </div>
                        </div>
                        <!-- Reprovada -->
                        <div class="flex flex-col w-[80%] rounded-lg mb-3 border-l-8 border-r border-t border-b border-l-[#950606] border-r-[#950606]/20 border-t-[#950606]/20 border-b-[#950606]/20 bg-[#F4ECE6]/50 p-3">
                            <div class="flex flex-row items-center gap-3.5">
                                <font-awesome-icon
                                    :icon="['far', 'circle-xmark']"
                                    class="text-2xl text-[#950606]"
                                />
                                <div class="flex flex-col">
                                    <h4 class="text-[#950606] mb-1 font-bold">Resultado: Regra de negócio reprovada!</h4>
                                    <ul class="list-disc list-inside">
                                        <li class="text-[#584237]">A regra de negócio NÃO cabe no seu orçamento.</li>
                                    </ul>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    <!-- Sugestão (tornar aparição dinâmica depois) -->
        <div class="mb-8">
            <div class="mb-11">
                <h1 class="text-3xl text-[#2B160D] mb-2">Sugestão</h1>
                <p class="text-[#584237]">A regra de negócio escolhida é inviável. Mas não se preocupe, criamos esta para você:</p>
            </div>
            <div>
                <div class="flex flex-row">
                    <div class="w-[50%]">
                        <h3 class="font-bold">Regra estruturada</h3>
                        <hr class="mb-4 border border-[#FFDBCD] w-[89%]">
                            <form class="flex flex-row gap-22">
                                <div class="flex flex-col">
                                    <div class="flex flex-col">
                                        <label for="vigencia" class="mb-1 text-[#584237]">Vigência</label>
                                        <input id="vigencia" type="text" class="bg-[#FFE9E1] text-[#2B160D] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]"/>
                                    </div>
                                    <div class="flex flex-col">
                                        <label for="loja" class="mb-1 text-[#584237]">Loja</label>
                                        <input id="loja" type="text" class="bg-[#FFE9E1] text-[#2B160D] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]"/>
                                    </div>

                                    <div class="flex flex-col">
                                        <label for="marca" class="mb-1 text-[#584237]">Marca</label>
                                        <input id="marca" type="text" class="bg-[#FFE9E1] text-[#2B160D] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]" />
                                    </div>
                                </div>
                                <div class="flex flex-col">
                                    <label for="cargo" class="mb-1 text-[#584237]">Cargo</label>
                                    <input id="cargo" type="text" class="bg-[#FFE9E1] text-[#2B160D] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]"/>

                                    <label for="meta" class="mb-1 text-[#584237]">Meta</label>
                                    <input id="meta" type="text" class="bg-[#FFE9E1] text-[#2B160D] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]"/>

                                    <label for="percentual" class="mb-1 text-[#584237]">Percentual</label>
                                    <input id="percentual" type="text" class="bg-[#FFE9E1] text-[#2B160D] rounded-lg border-2 border-[#8B7265]/10 px-3.5 py-3 w-[14.5vw]"/>
                                </div>
                            </form>
                    </div>
                    <div class="border-2 border-[#DFC0B2] rounded-lg w-[50%] p-5">
                        <h3 class="font-bold">Dados da simulação</h3>
                        <hr class="mb-4 border border-[#FFDBCD]">
                        <div class="flex flex-col mb-8">
                            <label for="percentual" class="mb-1 text-[#584237]">Total de comissionamento</label>
                            <input id="percentual" type="text" placeholder="R$ X,00"  class="bg-[#FFE9E1] rounded-lg border-2 border-[#8B7265] text-[#2B160D] px-3.5 py-3 w-full"/>
                        </div>
                        <p class="text-lg mb-3">Deseja escolher essa nova regra?</p>
                        <div class="flex flex-row justify-around p-0 mb-3 gap-16">
                            <!-- SIM -->
                            <button class="flex flex-col w-[50%] h-fit rounded-lg border-l-8 border-r border-t border-b border-l-[#14532D] border-r-#14532D]/20 border-t-[#14532D]/20 border-b-[#14532D]/20 bg-[#F4ECE6]/50 p-3 items-center justify-center">
                                <div class="flex flex-col items-center">
                                    <h4 class="text-[#14532D] font-bold">SIM!</h4>
                                    <span class="text-[#584237]">Seguir para a próxima etapa.</span>
                                </div>
                            </button>
                            <!-- NÃO -->
                            <button class="flex flex-col w-[50%] h-fit rounded-lg border-l-8 border-r border-t border-b border-l-[#950606] border-r-[#950606]/20 border-t-[#950606]/20 border-b-[#950606]/20 bg-[#F4ECE6]/50 p-3 items-center justify-center">
                                <div class="flex flex-col items-center">
                                    <h4 class="text-[#950606] font-bold">Não.</h4>
                                    <span class="text-[#584237]">Cancelar este fluxo.</span>
                                </div>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</template>