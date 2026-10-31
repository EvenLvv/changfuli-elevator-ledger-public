import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import App from './App.vue'
import './style.css'

const routes = [
  '/', '/elevators', '/elevators/:id', '/events/new', '/events/:id/edit',
  '/records', '/search', '/reminders', '/export', '/admin'
].map(path => ({path, component: {render: () => null}}))
const router = createRouter({history:createWebHistory(), routes})
createApp(App).use(router).use(ElementPlus,{locale:zhCn}).mount('#app')
