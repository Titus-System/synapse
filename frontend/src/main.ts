import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { library } from '@fortawesome/fontawesome-svg-core'
import { FontAwesomeIcon } from '@fortawesome/vue-fontawesome'
import { faCircleXmark } from '@fortawesome/free-regular-svg-icons'
import { faCircleCheck } from '@fortawesome/free-regular-svg-icons'

import App from './App.vue'
import roteador from './router'
import { instalarRegistroDeErrosDoNavegador } from './observability/browserErrorLogging'

import './assets/main.css'

library.add(faCircleXmark)
library.add(faCircleCheck)

const aplicacao = createApp(App)

aplicacao.component('font-awesome-icon', FontAwesomeIcon)
aplicacao.use(createPinia())
aplicacao.use(roteador)
instalarRegistroDeErrosDoNavegador(aplicacao)

aplicacao.mount('#app')
