// ===== DOM Ready =====
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 SMM Panel loaded');
    
    // Auto-hide flash messages after 5 seconds
    const flashMessages = document.querySelectorAll('.flash-message');
    flashMessages.forEach(msg => {
        setTimeout(() => {
            msg.style.transition = 'opacity 0.5s';
            msg.style.opacity = '0';
            setTimeout(() => msg.remove(), 500);
        }, 5000);
    });
    
    // ===== Copy to Clipboard =====
    document.querySelectorAll('.copy-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            const target = document.querySelector(this.dataset.target);
            if (target) {
                const text = target.textContent || target.value;
                navigator.clipboard.writeText(text).then(() => {
                    const original = this.innerHTML;
                    this.innerHTML = '<i class="fa-regular fa-check"></i> Copied!';
                    setTimeout(() => this.innerHTML = original, 2000);
                });
            }
        });
    });
    
    // ===== Confirm Delete =====
    document.querySelectorAll('.confirm-delete').forEach(btn => {
        btn.addEventListener('click', function(e) {
            if (!confirm('Are you sure you want to delete this?')) {
                e.preventDefault();
            }
        });
    });
    
    // ===== Toggle Visibility =====
    document.querySelectorAll('.toggle-visibility').forEach(btn => {
        btn.addEventListener('click', function() {
            const target = document.querySelector(this.dataset.target);
            if (target) {
                if (target.type === 'password') {
                    target.type = 'text';
                    this.innerHTML = '<i class="fa-regular fa-eye-slash"></i>';
                } else {
                    target.type = 'password';
                    this.innerHTML = '<i class="fa-regular fa-eye"></i>';
                }
            }
        });
    });
    
    // ===== Dynamic Order Calculator =====
    const quantityInput = document.getElementById('quantity');
    const rateDisplay = document.getElementById('rate-display');
    const totalDisplay = document.getElementById('total-display');
    
    if (quantityInput && rateDisplay && totalDisplay) {
        quantityInput.addEventListener('input', function() {
            const quantity = parseInt(this.value) || 0;
            const rate = parseFloat(rateDisplay.dataset.rate) || 0;
            const markup = parseFloat(rateDisplay.dataset.markup) || 15;
            const total = (quantity / 1000) * rate * (1 + markup / 100);
            totalDisplay.textContent = '$' + total.toFixed(2);
        });
    }
    
    // ===== Service Filter =====
    const categoryFilter = document.getElementById('category-filter');
    const searchFilter = document.getElementById('search-filter');
    const serviceCards = document.querySelectorAll('.service-card');
    
    if (categoryFilter && serviceCards.length) {
        categoryFilter.addEventListener('change', filterServices);
        if (searchFilter) searchFilter.addEventListener('input', filterServices);
    }
    
    function filterServices() {
        const category = categoryFilter ? categoryFilter.value : 'all';
        const search = searchFilter ? searchFilter.value.toLowerCase() : '';
        
        serviceCards.forEach(card => {
            const cardCategory = card.dataset.category || '';
            const cardName = card.dataset.name || '';
            const matchCategory = category === 'all' || cardCategory === category;
            const matchSearch = cardName.toLowerCase().includes(search);
            card.style.display = (matchCategory && matchSearch) ? '' : 'none';
        });
    }
    
    // ===== Modal System =====
    window.openModal = function(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.remove('hidden');
            document.body.style.overflow = 'hidden';
        }
    };
    
    window.closeModal = function(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add('hidden');
            document.body.style.overflow = '';
        }
    };
    
    // Close modal on overlay click
    document.querySelectorAll('.modal-overlay').forEach(overlay => {
        overlay.addEventListener('click', function(e) {
            if (e.target === this) {
                this.classList.add('hidden');
                document.body.style.overflow = '';
            }
        });
    });
    
    // ===== AJAX Form Submit =====
    document.querySelectorAll('.ajax-form').forEach(form => {
        form.addEventListener('submit', async function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            const method = this.method || 'POST';
            const url = this.action || window.location.href;
            const responseDiv = document.getElementById(this.dataset.response || 'response');
            
            try {
                const response = await fetch(url, {
                    method: method,
                    body: formData
                });
                const data = await response.json();
                
                if (data.success) {
                    if (responseDiv) {
                        responseDiv.innerHTML = `<div class="alert alert-success">${data.message || 'Success!'}</div>`;
                    }
                    if (this.dataset.reload) {
                        setTimeout(() => window.location.reload(), 1500);
                    }
                    if (this.dataset.reset) {
                        this.reset();
                    }
                } else {
                    if (responseDiv) {
                        responseDiv.innerHTML = `<div class="alert alert-danger">${data.error || data.message || 'Error!'}</div>`;
                    }
                }
            } catch (error) {
                if (responseDiv) {
                    responseDiv.innerHTML = `<div class="alert alert-danger">Network error: ${error.message}</div>`;
                }
            }
        });
    });
    
    // ===== API Key Generator =====
    document.querySelectorAll('.generate-api-key').forEach(btn => {
        btn.addEventListener('click', function() {
            const key = 'sk_' + Math.random().toString(36).substring(2, 15) + 
                        Math.random().toString(36).substring(2, 15);
            const target = document.querySelector(this.dataset.target);
            if (target) {
                target.value = key;
            }
        });
    });
    
    // ===== Status Update =====
    document.querySelectorAll('.status-update').forEach(select => {
        select.addEventListener('change', async function() {
            const id = this.dataset.id;
            const status = this.value;
            const url = this.dataset.url || window.location.href;
            
            try {
                const response = await fetch(url, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ status: status })
                });
                const data = await response.json();
                
                if (data.success) {
                    this.style.borderColor = '#22c55e';
                    setTimeout(() => this.style.borderColor = '', 1000);
                } else {
                    alert('Error updating status');
                }
            } catch (error) {
                alert('Network error');
            }
        });
    });
    
    // ===== Service Price Calculator =====
    function calculatePrice(rate, quantity, markup) {
        return (quantity / 1000) * rate * (1 + markup / 100);
    }
    
    // ===== Format Currency =====
    window.formatCurrency = function(amount) {
        return '$' + Number(amount).toFixed(2);
    };

    // 1. Cost (USD)
const costUsd = (quantity / 1000) * rate;

// 2. Original price (MMK) with markup
const originalPrice = costUsd * EXCHANGE_RATE * (1 + serviceMarkup / 100);

// 3. Apply discount
const discountPct = userDiscountPercent || 0;
const discountAmountVal = originalPrice * (discountPct / 100);
const priceAfterDiscount = originalPrice - discountAmountVal;

// 4. Bonus
let bonusValue = 0;
if (bonusAmount > 0) {
    bonusValue = (bonusType === 'percentage') ? priceAfterDiscount * (bonusAmount / 100) : bonusAmount;
}

// 5. Final price
const finalPrice = priceAfterDiscount;
const remaining = initialBalance - finalPrice;
    
// Markup Form Submit
document.getElementById('markupForm').addEventListener('submit', function(e) {
    e.preventDefault();
    const data = {
        user_default_markup: document.getElementById('userDefaultMarkup').value,
        reseller_default_markup: document.getElementById('resellerDefaultMarkup').value,
        user_discount: document.getElementById('userDiscount').value,
        reseller_discount: document.getElementById('resellerDiscount').value,
        order_bonus: document.getElementById('orderBonus').value,
        bonus_type: document.getElementById('bonusType').value
    };

    fetch('/admin/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
    .then(res => res.json())
    .then(() => {
        showMessage('✅ အမြတ်နှုန်းနှင့် လျှော့စျေးများ သိမ်းဆည်းပြီးပါပြီ။', 'success');
        setTimeout(() => location.reload(), 1500);
    })
    .catch(err => {
        showMessage('❌ Error: ' + err.message, 'error');
    });
});

    // ===== Format Date =====
    window.formatDate = function(dateString) {
        if (!dateString) return 'N/A';
        const date = new Date(dateString);
        return date.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    };
    
    console.log('✅ SMM Panel scripts loaded successfully');
});

// ===== DELETE ALL SERVICES =====

function deleteAllServices() {
    if (!confirm('⚠️ ဝန်ဆောင်မှုအားလုံးကို ဖျက်မှာ သေချာလား?\n\nဒီလုပ်ဆောင်ချက်က ပြန်မဖျက်နိုင်ပါ။')) return;
    if (!confirm('နောက်ဆုံးအနေနဲ့ သေချာပြီလား? အကုန်ဖျက်ပစ်မှာပါ။')) return;

    const msgDiv = document.getElementById('syncMessage');
    msgDiv.className = 'mb-5 p-3 rounded-xl text-sm glass-card border border-rose-500/20 text-rose-400';
    msgDiv.innerHTML = '<i class="fa-solid fa-spinner fa-spin mr-2"></i> ဝန်ဆောင်မှုများကို ဖျက်နေပါသည်...';
    msgDiv.classList.remove('hidden');

    fetch('/admin/services/delete-all', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            msgDiv.className = 'mb-5 p-3 rounded-xl text-sm glass-card border border-emerald-500/20 text-emerald-400';
            msgDiv.innerHTML = '<i class="fa-solid fa-check-circle mr-2"></i> ' + data.message;
            setTimeout(() => location.reload(), 1500);
        } else {
            msgDiv.className = 'mb-5 p-3 rounded-xl text-sm glass-card border border-rose-500/20 text-rose-400';
            msgDiv.innerHTML = '<i class="fa-solid fa-exclamation-circle mr-2"></i> ' + (data.error || 'ဖျက်ရာတွင် အမှားရှိပါသည်။');
        }
    })
    .catch(err => {
        msgDiv.className = 'mb-5 p-3 rounded-xl text-sm glass-card border border-rose-500/20 text-rose-400';
        msgDiv.innerHTML = '<i class="fa-solid fa-exclamation-circle mr-2"></i> Error: ' + err.message;
    });
}