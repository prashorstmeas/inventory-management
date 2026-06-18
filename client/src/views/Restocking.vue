<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div class="card">
      <div class="card-header">
        <h3 class="card-title">{{ t('restocking.budget') }}</h3>
      </div>
      <div class="budget-control">
        <input
          type="range"
          min="0"
          max="10000"
          step="100"
          v-model.number="budget"
          class="budget-slider"
        />
        <div class="budget-display">{{ currencySymbol }}{{ budget.toLocaleString() }}</div>
      </div>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div v-if="submitSuccess" class="success-message">{{ submitSuccess }}</div>
      <div v-if="submitError" class="error">{{ submitError }}</div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendedItems') }}</h3>
        </div>

        <div v-if="recommendedItems.length === 0" class="empty-state">
          {{ t('restocking.noRecommendations') }}
        </div>
        <div v-else>
          <div class="stats-grid">
            <div class="stat-card info">
              <div class="stat-label">{{ t('restocking.totalCost') }}</div>
              <div class="stat-value">{{ currencySymbol }}{{ totalCost.toLocaleString() }}</div>
            </div>
            <div class="stat-card success">
              <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
              <div class="stat-value">{{ currencySymbol }}{{ remainingBudget.toLocaleString() }}</div>
            </div>
            <div class="stat-card warning">
              <div class="stat-label">{{ t('restocking.itemsRecommended') }}</div>
              <div class="stat-value">{{ recommendedItems.length }}</div>
            </div>
          </div>

          <div class="table-container">
            <table>
              <thead>
                <tr>
                  <th class="col-checkbox"></th>
                  <th>{{ t('restocking.table.sku') }}</th>
                  <th>{{ t('restocking.table.itemName') }}</th>
                  <th>{{ t('restocking.table.trend') }}</th>
                  <th>{{ t('restocking.table.currentDemand') }}</th>
                  <th>{{ t('restocking.table.forecastedDemand') }}</th>
                  <th>{{ t('restocking.table.restockQty') }}</th>
                  <th>{{ t('restocking.table.unitCost') }}</th>
                  <th>{{ t('restocking.table.itemCost') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in recommendedItems" :key="item.item_sku">
                  <td class="col-checkbox">
                    <input
                      type="checkbox"
                      :checked="selectedSkus.has(item.item_sku)"
                      @change="toggleSku(item.item_sku)"
                    />
                  </td>
                  <td><strong>{{ item.item_sku }}</strong></td>
                  <td>{{ item.item_name }}</td>
                  <td>
                    <span :class="['badge', item.trend]">
                      {{ t(`trends.${item.trend}`) }}
                    </span>
                  </td>
                  <td>{{ item.current_demand }}</td>
                  <td>{{ item.forecasted_demand }}</td>
                  <td>{{ item.restock_qty }}</td>
                  <td>{{ currencySymbol }}{{ item.unit_cost.toLocaleString() }}</td>
                  <td><strong>{{ currencySymbol }}{{ item.item_cost.toLocaleString() }}</strong></td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="place-order-row">
            <button
              class="place-order-btn"
              :disabled="selectedSkus.size === 0 || submitting"
              @click="placeOrder"
            >
              {{ submitting ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency } = useI18n()

    const currencySymbol = computed(() => {
      return currentCurrency.value === 'JPY' ? '¥' : '$'
    })

    const loading = ref(true)
    const error = ref(null)
    const budget = ref(5000)

    const recommendedItems = ref([])
    const totalCost = ref(0)
    const remainingBudget = ref(0)
    const selectedSkus = ref(new Set())

    const submitting = ref(false)
    const submitSuccess = ref(null)
    const submitError = ref(null)

    let debounceTimer = null

    const loadRecommendations = async () => {
      try {
        loading.value = true
        error.value = null
        const data = await api.getRestockRecommendations(budget.value)
        recommendedItems.value = data.recommended_items
        totalCost.value = data.total_cost
        remainingBudget.value = data.remaining_budget
        // Default to all-checked whenever new recommendations load
        selectedSkus.value = new Set(data.recommended_items.map(item => item.item_sku))
      } catch (err) {
        error.value = 'Failed to load restock recommendations: ' + err.message
      } finally {
        loading.value = false
      }
    }

    watch(budget, () => {
      submitSuccess.value = null
      submitError.value = null
      if (debounceTimer) clearTimeout(debounceTimer)
      debounceTimer = setTimeout(() => {
        loadRecommendations()
      }, 400)
    })

    const toggleSku = (sku) => {
      const updated = new Set(selectedSkus.value)
      if (updated.has(sku)) {
        updated.delete(sku)
      } else {
        updated.add(sku)
      }
      selectedSkus.value = updated
    }

    const placeOrder = async () => {
      submitting.value = true
      submitSuccess.value = null
      submitError.value = null

      try {
        const items = recommendedItems.value
          .filter(item => selectedSkus.value.has(item.item_sku))
          .map(item => ({
            sku: item.item_sku,
            name: item.item_name,
            quantity: item.restock_qty,
            unit_price: item.unit_cost
          }))

        const result = await api.submitRestockOrder({
          budget: budget.value,
          items
        })

        submitSuccess.value = t('restocking.orderSuccess', { orderNumber: result.order.order_number })
        await loadRecommendations()
      } catch (err) {
        submitError.value = t('restocking.orderError')
        console.error('Failed to submit restock order:', err)
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadRecommendations)

    return {
      t,
      loading,
      error,
      budget,
      currencySymbol,
      recommendedItems,
      totalCost,
      remainingBudget,
      selectedSkus,
      toggleSku,
      submitting,
      submitSuccess,
      submitError,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-control {
  display: flex;
  align-items: center;
  gap: 1.5rem;
}

.budget-slider {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: #e2e8f0;
  appearance: none;
  -webkit-appearance: none;
  outline: none;
  cursor: pointer;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #2563eb;
  cursor: pointer;
  transition: background 0.2s ease;
}

.budget-slider::-webkit-slider-thumb:hover {
  background: #1d4ed8;
}

.budget-slider::-moz-range-thumb {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #2563eb;
  cursor: pointer;
  border: none;
  transition: background 0.2s ease;
}

.budget-slider::-moz-range-thumb:hover {
  background: #1d4ed8;
}

.budget-display {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
  min-width: 120px;
  text-align: right;
  letter-spacing: -0.025em;
}

.empty-state {
  text-align: center;
  padding: 3rem;
  color: #64748b;
  font-size: 0.938rem;
}

.col-checkbox {
  width: 40px;
}

.place-order-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 1.25rem;
}

.place-order-btn {
  padding: 0.625rem 1.5rem;
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 0.938rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease;
}

.place-order-btn:hover:not(:disabled) {
  background: #1d4ed8;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.success-message {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #166534;
  padding: 1rem;
  border-radius: 8px;
  margin: 1rem 0;
  font-size: 0.938rem;
}
</style>
