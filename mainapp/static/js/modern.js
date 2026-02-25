// modern.js - helper scripts for modern UI enhancements

// add 'scrolled' class to navbar when user scrolls down
(function() {
    var navbar = document.querySelector('.navbar');
    if (!navbar) return;

    function checkScroll() {
        if (window.scrollY > 50) {
            navbar.classList.add('scrolled');
        } else {
            navbar.classList.remove('scrolled');
        }
    }

    window.addEventListener('scroll', checkScroll);
    document.addEventListener('DOMContentLoaded', checkScroll);
})();

// additional interactions can be added here in future
