import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { library } from '@fortawesome/fontawesome-svg-core'
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'
import { faCircleXmark } from '@fortawesome/free-regular-svg-icons'
import { faCircleCheck } from '@fortawesome/free-regular-svg-icons'
import { faCircleExclamation } from '@fortawesome/free-solid-svg-icons'
import { faDiagramProject } from '@fortawesome/free-solid-svg-icons'
import { faFlask } from '@fortawesome/free-solid-svg-icons'

import App from './App.vue'
import roteador from './router'
import { instalarRegistroDeErrosDoNavegador } from './observability/browserErrorLogging'
import { usarStoreSessao } from './stores/session'

import './assets/main.css'

library.add(faCircleXmark)
library.add(faCircleCheck)
library.add(faCircleExclamation)
library.add(faDiagramProject)
library.add(faFlask)

const aplicacao = createApp(App)
const pinia = createPinia()

aplicacao.component('font-awesome-icon', FontAwesomeIcon)
aplicacao.use(pinia)
await usarStoreSessao(pinia).inicializar()
aplicacao.use(roteador)
instalarRegistroDeErrosDoNavegador(aplicacao)

aplicacao.mount('#app')
