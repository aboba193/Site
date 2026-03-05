const cars = [
  {
    name: "Tenet Falcon X5",
    type: "suv",
    year: 2025,
    fuel: "Hybrid",
    price: 48900,
    image:
      "https://images.unsplash.com/photo-1552519507-da3b142c6e3d?auto=format&fit=crop&w=1200&q=80"
  },
  {
    name: "Tenet Nova S",
    type: "sedan",
    year: 2024,
    fuel: "Petrol",
    price: 37200,
    image:
      "https://images.unsplash.com/photo-1492144534655-ae79c964c9d7?auto=format&fit=crop&w=1200&q=80"
  },
  {
    name: "Tenet Volt R",
    type: "electric",
    year: 2026,
    fuel: "EV",
    price: 55900,
    image:
      "https://images.unsplash.com/photo-1617469767053-d3b523a0b982?auto=format&fit=crop&w=1200&q=80"
  },
  {
    name: "Tenet Horizon Q7",
    type: "suv",
    year: 2025,
    fuel: "Diesel",
    price: 51900,
    image:
      "https://images.unsplash.com/photo-1549921296-3c7b6f4d8f4a?auto=format&fit=crop&w=1200&q=80"
  },
  {
    name: "Tenet Aero LX",
    type: "sedan",
    year: 2026,
    fuel: "Hybrid",
    price: 42800,
    image:
      "https://images.unsplash.com/photo-1617531653520-4893f7db7061?auto=format&fit=crop&w=1200&q=80"
  },
  {
    name: "Tenet Pulse E3",
    type: "electric",
    year: 2025,
    fuel: "EV",
    price: 46900,
    image:
      "https://images.unsplash.com/photo-1597007030739-6d2e0fa7f2f4?auto=format&fit=crop&w=1200&q=80"
  }
];

const testimonials = [
  {
    text: "Best dealership process I have had. No hidden extras, quick paperwork, and honest trade-in.",
    author: "Daniel K. - Falcon X5 Owner"
  },
  {
    text: "The financing team got me approved in one day and explained every number before signing.",
    author: "Martha L. - Nova S Owner"
  },
  {
    text: "Test drive, valuation, and delivery all happened in one weekend. Smooth experience end to end.",
    author: "Chris P. - Volt R Owner"
  }
];

const carGrid = document.getElementById("carGrid");
const filters = document.getElementById("filters");
const priceInput = document.getElementById("carPrice");
const downInput = document.getElementById("downPayment");
const termSelect = document.getElementById("term");
const priceValue = document.getElementById("priceValue");
const downValue = document.getElementById("downValue");
const monthlyPayment = document.getElementById("monthlyPayment");
const quoteText = document.getElementById("quoteText");
const quoteAuthor = document.getElementById("quoteAuthor");
const contactForm = document.getElementById("contactForm");
const formMsg = document.getElementById("formMsg");
const submitBtn = document.getElementById("submitBtn");
const menuBtn = document.getElementById("menuBtn");
const navMenu = document.getElementById("navMenu");

function formatMoney(value) {
  return `$${Number(value).toLocaleString("en-US")}`;
}

function renderCars(filter = "all") {
  const list = filter === "all" ? cars : cars.filter((car) => car.type === filter);

  carGrid.innerHTML = list
    .map(
      (car) => `
      <article class="car-card">
        <div class="car-image" style="background-image:url('${car.image}')" role="img" aria-label="${car.name}"></div>
        <div class="car-body">
          <h3>${car.name}</h3>
          <p class="car-meta">${car.year} | ${car.fuel}</p>
          <div class="car-price">${formatMoney(car.price)}</div>
        </div>
      </article>
    `
    )
    .join("");
}

filters.addEventListener("click", (event) => {
  const button = event.target.closest(".filter");
  if (!button) {
    return;
  }

  filters.querySelectorAll(".filter").forEach((item) => item.classList.remove("is-active"));
  button.classList.add("is-active");
  renderCars(button.dataset.filter);
});

function updatePayment() {
  const price = Number(priceInput.value);
  const down = Number(downInput.value);
  const months = Number(termSelect.value);
  const annualRate = 0.059;
  const monthlyRate = annualRate / 12;
  const principal = Math.max(price - down, 0);
  const factor = Math.pow(1 + monthlyRate, months);
  const payment = principal === 0 ? 0 : (principal * monthlyRate * factor) / (factor - 1);

  priceValue.textContent = formatMoney(price);
  downValue.textContent = formatMoney(down);
  monthlyPayment.textContent = formatMoney(Math.round(payment));
}

let quoteIndex = 0;
function showQuote(index) {
  quoteText.textContent = testimonials[index].text;
  quoteAuthor.textContent = testimonials[index].author;
}

function rotateQuotes() {
  quoteIndex = (quoteIndex + 1) % testimonials.length;
  showQuote(quoteIndex);
}

contactForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const fullName = document.getElementById("fullName").value.trim();
  const email = document.getElementById("email").value.trim();
  const phone = document.getElementById("phone").value.trim();

  if (!fullName || !email || !phone) {
    formMsg.textContent = "Заполните все поля.";
    return;
  }

  submitBtn.disabled = true;
  formMsg.textContent = "Отправляем заявку...";

  try {
    const response = await fetch("/api/leads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fullName, email, phone })
    });

    const payload = await response.json();

    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "Ошибка отправки");
    }

    formMsg.textContent = "Заявка отправлена. Мы скоро свяжемся с вами.";
    contactForm.reset();
  } catch (error) {
    const details = error instanceof Error ? error.message : "Неизвестная ошибка";
    formMsg.textContent = `Не удалось отправить заявку: ${details}`;
  } finally {
    submitBtn.disabled = false;
  }
});

menuBtn.addEventListener("click", () => {
  const expanded = menuBtn.getAttribute("aria-expanded") === "true";
  menuBtn.setAttribute("aria-expanded", String(!expanded));
  navMenu.classList.toggle("is-open");
});

navMenu.querySelectorAll("a").forEach((link) => {
  link.addEventListener("click", () => {
    navMenu.classList.remove("is-open");
    menuBtn.setAttribute("aria-expanded", "false");
  });
});

const revealObserver = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("is-visible");
      }
    });
  },
  { threshold: 0.2 }
);

document.querySelectorAll(".reveal").forEach((section) => revealObserver.observe(section));

priceInput.addEventListener("input", updatePayment);
downInput.addEventListener("input", updatePayment);
termSelect.addEventListener("change", updatePayment);

renderCars();
updatePayment();
showQuote(quoteIndex);
setInterval(rotateQuotes, 4500);
