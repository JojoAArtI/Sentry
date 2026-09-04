// Sentry Dashboard Client Logic

document.addEventListener('DOMContentLoaded', () => {
  fetchMandate();
  fetchAuditTrail();
  fetchStatus();
  setInterval(fetchStatus, 3000);
});

async function fetchMandate() {
  try {
    const res = await fetch('/api/mandate');
    const data = await res.json();
    const m = data.mandate;

    document.getElementById('mandate-max-amount').textContent = `₹${m.max_amount.toLocaleString('en-IN')} ${m.currency}`;
    document.getElementById('mandate-categories').textContent = JSON.stringify(m.allowed_categories);
    document.getElementById('mandate-max-qty').textContent = `${m.max_quantity} units`;
    document.getElementById('mandate-threshold').textContent = m.autonomous_threshold ? `₹${m.autonomous_threshold.toLocaleString('en-IN')} INR` : 'None';
    document.getElementById('mandate-single-use').textContent = m.single_use ? 'YES (Single-use)' : 'NO (Multi-use)';
    document.getElementById('mandate-pubkey').textContent = data.public_key_hex.substring(0, 24) + '...';
    document.getElementById('mandate-sig').textContent = m.signature ? m.signature.substring(0, 24) + '... (Valid ✓)' : 'Unsigned';

    const pill = document.getElementById('mandate-status-pill');
    if (data.is_consumed) {
      pill.textContent = 'CONSUMED';
      pill.className = 'status-pill pill-invalid';
    } else if (data.is_signature_valid) {
      pill.textContent = 'VALID';
      pill.className = 'status-pill pill-valid';
    } else {
      pill.textContent = 'INVALID SIG';
      pill.className = 'status-pill pill-invalid';
    }
  } catch (err) {
    console.error('Failed to fetch mandate:', err);
  }
}

async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    document.getElementById('rzp-calls-display').textContent = `${data.razorpay_call_count} API CALLS MADE`;

    const approvalCard = document.getElementById('approval-card');
    if (data.has_pending_approval && data.pending_approval) {
      approvalCard.style.display = 'block';
      const p = data.pending_approval.proposal;
      document.getElementById('approval-details-text').textContent =
        `Item: ${p.item_name} (${p.sku}) | Qty: ${p.quantity} | Total: ₹${p.total_amount.toLocaleString('en-IN')} | Threshold: ₹${data.pending_approval.threshold.toLocaleString('en-IN')}`;
    } else {
      approvalCard.style.display = 'none';
    }
  } catch (err) {
    console.error('Failed to fetch status:', err);
  }
}

async function fetchAuditTrail() {
  try {
    const res = await fetch('/api/audit?limit=20');
    const events = await res.json();
    const tbody = document.getElementById('audit-tbody');
    tbody.innerHTML = '';

    if (events.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" class="text-center">No audit records yet.</td></tr>';
      return;
    }

    events.forEach(ev => {
      const tr = document.createElement('tr');
      const timeStr = ev.timestamp ? ev.timestamp.substring(11, 19) : '--:--:--';
      
      let verdictBadge = '-';
      if (ev.decision === 'APPROVED') {
        verdictBadge = '<span class="verdict-tag tag-approved">APPROVED</span>';
      } else if (ev.decision === 'REJECTED') {
        verdictBadge = '<span class="verdict-tag tag-rejected">BLOCKED</span>';
      } else if (ev.decision) {
        verdictBadge = `<span class="verdict-tag tag-pending">${ev.decision}</span>`;
      }

      const rzpCalledHtml = ev.razorpay_called
        ? '<span class="rzp-called-yes">YES ✓</span>'
        : '<span class="rzp-called-no">NO ✗ (0 Calls)</span>';

      tr.innerHTML = `
        <td>${timeStr}</td>
        <td><strong>${ev.event}</strong></td>
        <td><code>${ev.mandate_id || '-'}</code></td>
        <td>${ev.sku || '-'}</td>
        <td>${ev.quantity ?? '-'}</td>
        <td>${ev.requested_total ? '₹' + ev.requested_total.toLocaleString('en-IN') : '-'}</td>
        <td>${verdictBadge}</td>
        <td><small>${ev.reason || '-'}</small></td>
        <td>${rzpCalledHtml}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error('Failed to fetch audit:', err);
  }
}

async function runScenario(scenarioName) {
  const feed = document.getElementById('agent-activity-feed');
  feed.innerHTML = '<div class="feed-item"><span class="feed-desc">Agent spinning up...</span></div>';

  try {
    const res = await fetch('/api/demo/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario: scenarioName })
    });
    const data = await res.json();
    const output = data.output;

    // Render agent feed
    renderAgentFeed(output.agent_activity);

    // Render verdict
    renderVerdict(output.result, output.proposal);

    // Refresh state
    await fetchMandate();
    await fetchAuditTrail();
    await fetchStatus();
  } catch (err) {
    alert('Error executing scenario: ' + err.message);
  }
}

function renderAgentFeed(activities) {
  const feed = document.getElementById('agent-activity-feed');
  feed.innerHTML = '';

  activities.forEach(act => {
    const item = document.createElement('div');
    item.className = 'feed-item';

    if (act.step === 'list_products') item.classList.add('step-browse');
    else if (act.step === 'get_product') item.classList.add('step-inspect');
    else if (act.step === 'adversarial_content_detected') item.classList.add('step-injection');
    else if (act.step === 'propose_purchase') item.classList.add('step-propose');
    else if (act.step === 'verdict_received') item.classList.add('step-verdict');

    const title = document.createElement('div');
    title.className = 'feed-item-title';
    title.textContent = `[${act.step.toUpperCase()}]`;

    const desc = document.createElement('div');
    desc.className = 'feed-item-desc';
    desc.textContent = act.details.message || JSON.stringify(act.details);

    item.appendChild(title);
    item.appendChild(desc);
    feed.appendChild(item);
  });
}

function renderVerdict(result, proposal) {
  const container = document.getElementById('verdict-panel');
  const rzpOrderDisplay = document.getElementById('rzp-order-display');
  const d = result.decision;

  if (d.decision === 'APPROVED') {
    const orderId = result.order ? result.order.id : 'N/A';
    container.innerHTML = `
      <div class="verdict-box approved">
        <div class="verdict-title">✓ TRANSACTION AUTHORIZED</div>
        <div class="verdict-reason">${d.reason}</div>
        <div class="verdict-stats">
          <span>AMOUNT: ₹${proposal.total_amount.toLocaleString('en-IN')}</span>
          <span>QUANTITY: ${proposal.quantity}</span>
          <span>STATUS: WITHIN MANDATE</span>
        </div>
      </div>
    `;
    rzpOrderDisplay.textContent = `Order Created: ${orderId} (${result.order?.currency || 'INR'})`;
  } else if (d.decision === 'REJECTED') {
    container.innerHTML = `
      <div class="verdict-box rejected">
        <div class="verdict-title">🛑 TRANSACTION BLOCKED</div>
        <div class="verdict-reason">${d.reason}</div>
        <div class="verdict-stats">
          <span>REQUESTED: ₹${proposal.total_amount.toLocaleString('en-IN')}</span>
          <span>REASON CODE: ${d.reason_code}</span>
        </div>
      </div>
    `;
    rzpOrderDisplay.textContent = `Razorpay API: NOT CALLED (0 Calls Made)`;
  } else if (d.decision === 'REQUIRES_HUMAN_APPROVAL') {
    container.innerHTML = `
      <div class="verdict-box" style="background: rgba(245, 158, 11, 0.1); border: 2px solid #f59e0b;">
        <div class="verdict-title" style="color: #f59e0b;">⚠️ REQUIRES HUMAN SIGN-OFF</div>
        <div class="verdict-reason">${d.reason}</div>
      </div>
    `;
    rzpOrderDisplay.textContent = `Payment Gated until human approval`;
  }
}

async function resolveApproval(action) {
  try {
    const res = await fetch('/api/approval/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action })
    });
    const data = await res.json();
    alert(`Human decision registered: ${data.status}`);
    await fetchMandate();
    await fetchAuditTrail();
    await fetchStatus();
  } catch (err) {
    alert('Error resolving approval: ' + err.message);
  }
}

async function resetMandate() {
  try {
    await fetch('/api/mandate/reset', { method: 'POST' });
    await fetchMandate();
    await fetchAuditTrail();
    await fetchStatus();
    document.getElementById('verdict-panel').innerHTML = `
      <div class="verdict-idle">
        <div class="idle-icon">🛡️</div>
        <p>Fresh mandate issued. Ready for transaction proposal.</p>
      </div>
    `;
    document.getElementById('rzp-order-display').textContent = 'No active order';
    document.getElementById('agent-activity-feed').innerHTML = `
      <div class="feed-item placeholder-item">
        <span class="feed-desc">Mandate reset. Ready for agent execution.</span>
      </div>
    `;
  } catch (err) {
    alert('Failed to reset mandate: ' + err.message);
  }
}
