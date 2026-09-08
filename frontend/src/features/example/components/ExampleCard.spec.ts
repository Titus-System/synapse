import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ExampleCard from './ExampleCard.vue'

describe('ExampleCard', () => {
  it('renders the item name', () => {
    const wrapper = mount(ExampleCard, {
      props: { item: { id: '1', name: 'First item' } },
    })

    expect(wrapper.text()).toContain('First item')
  })

  it('emits select with the id on click', async () => {
    const wrapper = mount(ExampleCard, {
      props: { item: { id: '42', name: 'Item' } },
    })

    await wrapper.get('button').trigger('click')

    expect(wrapper.emitted('select')).toEqual([['42']])
  })
})
