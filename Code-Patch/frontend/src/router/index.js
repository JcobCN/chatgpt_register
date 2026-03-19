import { createRouter, createWebHistory } from 'vue-router'
import RegisterView from '../views/RegisterView.vue'
import SessionsView from '../views/SessionsView.vue'
import AccountsView from '../views/AccountsView.vue'
import SchedulesView from '../views/SchedulesView.vue'

const routes = [
  { path: '/', redirect: '/register' },
  { path: '/register', component: RegisterView, name: 'Register' },
  { path: '/sessions', component: SessionsView, name: 'Sessions' },
  { path: '/accounts', component: AccountsView, name: 'Accounts' },
  { path: '/schedules', component: SchedulesView, name: 'Schedules' },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
