<template>
  <el-container class="app-layout">
    <el-aside class="sidebar" width="220px">
      <div class="sidebar-logo">
        <span class="logo-icon">⚡</span>
        <span class="logo-text">Code Patch</span>
      </div>
      <el-menu
        :router="true"
        :default-active="route.path"
        class="sidebar-menu"
      >
        <el-menu-item index="/register">
          <el-icon><UserFilled /></el-icon>
          <span>批量注册</span>
        </el-menu-item>
        <el-menu-item index="/sessions">
          <el-icon><List /></el-icon>
          <span>注册记录</span>
        </el-menu-item>
        <el-menu-item index="/accounts">
          <el-icon><DataAnalysis /></el-icon>
          <span>账号查询</span>
        </el-menu-item>
        <el-menu-item index="/schedules">
          <el-icon><AlarmClock /></el-icon>
          <span>任务中心</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-main class="page-main">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup>
import { useRoute } from 'vue-router'
const route = useRoute()
</script>

<style>
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif; }
</style>

<style scoped>
.app-layout {
  height: 100vh;
  overflow: hidden;
}

.sidebar {
  background: var(--color-sidebar-bg);
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.sidebar-logo {
  padding: 20px 16px 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, .06);
  margin-bottom: 4px;
}

.logo-icon {
  font-size: 20px;
}

.logo-text {
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: .5px;
}

.sidebar-menu {
  background-color: var(--color-sidebar-bg) !important;
  border-right: none !important;
  --el-menu-text-color: var(--color-sidebar-text);
  --el-menu-active-color: var(--color-sidebar-active);
  --el-menu-hover-bg-color: var(--color-sidebar-hover);
  --el-menu-bg-color: var(--color-sidebar-bg);
}

.page-main {
  background: var(--color-page-bg);
  padding: var(--space-xl);
  overflow-y: auto;
}
</style>
