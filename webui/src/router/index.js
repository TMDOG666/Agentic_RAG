import { createRouter, createWebHistory } from 'vue-router'

import Layout from '../views/Layout.vue'
import GroupsList from '../views/GroupsList.vue'
import GroupDetail from '../views/GroupDetail.vue'
import ApiDocs from '../views/ApiDocs.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: Layout,
      children: [
        { path: '', name: 'groups', component: GroupsList },
        { path: 'groups/:groupId', name: 'group', component: GroupDetail, props: true },
        { path: 'api-docs', name: 'api-docs', component: ApiDocs },
      ],
    },
  ],
})
