import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({plugins:[vue()],build:{target:'chrome109',outDir:'dist'},server:{proxy:{'/api':'http://127.0.0.1:8765'}}})
