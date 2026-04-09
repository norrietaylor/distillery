<script lang="ts">
  let appTitle = $state("Distillery Dashboard");
</script>

<main>
  <header>
    <h1>{appTitle}</h1>
  </header>
  <section id="home">
    <p>Loading knowledge base data...</p>
  </section>
</main>

<style>
  :global(*) {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }

  :global(body) {
    font-family: system-ui, -apple-system, sans-serif;
    background: var(--bg, #ffffff);
    color: var(--fg, #1a1a1a);
  }

  main {
    max-width: 1200px;
    margin: 0 auto;
    padding: 1rem;
  }

  header {
    border-bottom: 1px solid var(--border, #e5e7eb);
    padding-bottom: 1rem;
    margin-bottom: 1rem;
  }

  h1 {
    font-size: 1.5rem;
    font-weight: 600;
  }
</style>
