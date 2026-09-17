import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import roteador from './router'
import { instalarRegistroDeErrosDoNavegador } from './observability/browserErrorLogging'

import './assets/main.css'

const aplicacao = createApp(App)

aplicacao.use(createPinia())
aplicacao.use(roteador)
instalarRegistroDeErrosDoNavegador(aplicacao)

aplicacao.mount('#app')
